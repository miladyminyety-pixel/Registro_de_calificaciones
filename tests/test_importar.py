import io
import json
import re

import pytest

from app import importer
from app.db import connect

CSV = (
    "matricula;nombres;apellidos;grado;seccion\n"
    "T-001;Lucía;Gómez;5;a\n"
    "T-002;Pedro;Ramos;5to;A\n"
    "T-003;Rosa;Díaz;6to;B\n"
)


def subir(cliente, contenido, nombre="e.csv", **extra):
    datos = {"csrf_token": cliente.token, "accion": "previsualizar", "centro": "Liceo Nuevo",
             "nivel": "Secundaria", "archivo": (io.BytesIO(contenido), nombre)}
    datos.update(extra)
    return cliente.c.post("/importar", data=datos, content_type="multipart/form-data")


def confirmar(cliente, html, **extra):
    datos_json = re.search(r'name="datos" value="([^"]*)"', html).group(1)
    import html as h
    datos = {"csrf_token": cliente.token, "accion": "confirmar", "centro": "Liceo Nuevo",
             "nivel": "Secundaria", "datos": h.unescape(datos_json)}
    datos.update(extra)
    return cliente.c.post("/importar", data=datos)


# ---------------------------------------------------------------- lectura
def test_csv_punto_y_coma_y_coma_y_alias():
    a = importer.leer_archivo("a.csv", CSV.encode("utf-8-sig"))
    b = importer.leer_archivo("b.csv", "Matrícula,Nombre,Apellido,Curso,Letra\nX1,Ana,Paz,3,C\n".encode("cp1252"))
    assert [f["matricula"] for f in a] == ["T-001", "T-002", "T-003"] and a[0]["_fila"] == 2
    assert b[0]["nombres"] == "Ana" and b[0]["seccion"] == "C"


def test_xlsx_plantilla_se_lee():
    filas = importer.leer_archivo("p.xlsx", importer.plantilla_xlsx())
    assert len(filas) == 3 and filas[0]["nombres"] == "María" and filas[2]["condicion"] == "Repitente"


def test_plantilla_csv_se_lee():
    assert len(importer.leer_archivo("p.csv", importer.plantilla_csv())) == 3


@pytest.mark.parametrize("nombre,datos", [
    ("a.pdf", b"x"), ("a.csv", b""), ("a.csv", b"matricula;nombres\nA;B\n"),
    ("a.xlsx", b"no es excel"), ("a.csv", b"x" * (importer.MAX_BYTES + 1)),
])
def test_archivos_invalidos(nombre, datos):
    with pytest.raises(Exception) as exc:
        importer.leer_archivo(nombre, datos)
    assert exc.value.status == 422


def test_normalizar_grado():
    assert importer.normalizar_grado("5") == "5to" and importer.normalizar_grado("1ro") == "1ro"
    assert importer.normalizar_grado("3º") == "3ro" and importer.normalizar_grado("7") is None
    assert importer.normalizar_grado("abc") is None and importer.normalizar_grado("0") is None


# ---------------------------------------------------------------- validación
def test_validar_errores_y_duplicados(app):
    with app.app_context():
        db = connect(app.config)
        filas = importer.leer_archivo("a.csv", (
            "matricula;nombres;apellidos;grado;seccion\n"
            "D1;A;B;5;A\nD1;C;D;5;A\n;E;F;5;A\nD3;G;H;9;A\nD4;I;J;5;AAAA\n").encode())
        r = importer.validar(db, filas, 1, None, "Secundaria")
        assert r["resumen"]["nuevos"] == 1 and r["resumen"]["con_errores"] == 4
        assert any("repetida" in e["mensaje"] for e in r["errores"])
        db.close()


# ---------------------------------------------------------------- flujo web
def test_requiere_login(app):
    c = app.test_client()
    assert c.get("/importar").status_code == 302
    assert c.get("/importar/plantilla.csv").status_code == 302


def test_pagina_y_plantillas(cliente):
    html = cliente.get("/importar").get_data(as_text=True)
    assert "Importar estudiantes" in html and "plantilla.xlsx" in html
    x = cliente.get("/importar/plantilla.xlsx")
    assert x.status_code == 200 and x.data.startswith(b"PK")
    assert cliente.get("/importar/plantilla.csv").data.startswith(b"\xef\xbb\xbf")
    assert cliente.get("/importar/plantilla.pdf").status_code == 404


def test_post_sin_csrf_rechazado(cliente):
    r = cliente.c.post("/importar", data={"accion": "previsualizar"})
    assert r.status_code in (400, 403)


def test_previsualizar_no_guarda_y_confirmar_guarda(cliente, app):
    r = subir(cliente, CSV.encode())
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Vista previa" in html and "Lucía" in html
    with app.app_context():
        db = connect(app.config)
        assert db.scalar("SELECT COUNT(*) FROM estudiantes WHERE matricula LIKE 'T-%'") == 0
        db.close()
    r2 = confirmar(cliente, html, areas="1")
    assert r2.status_code == 200 and "Importación completada" in r2.get_data(as_text=True)
    with app.app_context():
        db = connect(app.config)
        assert db.scalar("SELECT COUNT(*) FROM estudiantes WHERE matricula LIKE 'T-%'") == 3
        assert db.scalar("SELECT COUNT(*) FROM secciones s JOIN centros c ON c.id=s.centro_id "
                         "WHERE c.nombre='Liceo Nuevo'") == 2
        db.close()
    # reimportar el mismo archivo no duplica nada
    html3 = subir(cliente, CSV.encode()).get_data(as_text=True)
    assert "Ya inscritos" in html3
    confirmar(cliente, html3, areas="1")
    with app.app_context():
        db = connect(app.config)
        assert db.scalar("SELECT COUNT(*) FROM estudiantes WHERE matricula LIKE 'T-%'") == 3
        assert db.scalar("SELECT COUNT(*) FROM inscripciones i JOIN estudiantes e ON e.id=i.estudiante_id "
                         "WHERE e.matricula LIKE 'T-%'") == 3
        db.close()


def test_confirmar_con_errores_bloquea_salvo_omitir(cliente, app):
    malo = CSV + "T-004;Sin;Grado;99;A\n"
    html = subir(cliente, malo.encode()).get_data(as_text=True)
    assert "Errores (1)" in html
    r = confirmar(cliente, html)
    assert r.status_code == 422 and "errores" in r.get_data(as_text=True)
    with app.app_context():
        db = connect(app.config)
        assert db.scalar("SELECT COUNT(*) FROM estudiantes WHERE matricula LIKE 'T-%'") == 0
        db.close()
    r = confirmar(cliente, html, omitir_errores="1")
    assert "Importación completada" in r.get_data(as_text=True)


def test_estudiante_en_otra_seccion_es_error(cliente):
    # el demo ya inscribe estudiantes en 5to A/B/C; reutilizamos una matrícula existente
    import sqlite3  # noqa: F401
    app = cliente.c.application
    with app.app_context():
        db = connect(app.config)
        mat = db.scalar("SELECT matricula FROM estudiantes ORDER BY id LIMIT 1")
        db.close()
    csv_ = f"matricula;nombres;apellidos;grado;seccion\n{mat};X;Y;3;Z\n"
    html = subir(cliente, csv_.encode()).get_data(as_text=True)
    assert "Ya está inscrito" in html


def test_datos_manipulados_se_revalidan(cliente):
    falsos = json.dumps([{"_fila": 2, "matricula": "", "nombres": "A", "apellidos": "B", "grado": "5", "seccion": "A"}])
    r = cliente.c.post("/importar", data={"csrf_token": cliente.token, "accion": "confirmar",
                                          "centro": "X", "nivel": "Secundaria", "datos": falsos})
    assert r.status_code == 422
    r = cliente.c.post("/importar", data={"csrf_token": cliente.token, "accion": "confirmar",
                                          "centro": "X", "nivel": "Secundaria", "datos": "no-json"})
    assert r.status_code == 422


def test_area_invalida_y_centro_vacio(cliente):
    assert subir(cliente, CSV.encode(), areas="9999").status_code == 422
    assert subir(cliente, CSV.encode(), centro="").status_code == 422
