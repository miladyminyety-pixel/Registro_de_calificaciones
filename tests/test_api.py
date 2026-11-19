"""Seguridad, autorización, validación y reglas de negocio de la API."""
import re

from app import create_app, security
from app.db import connect
from app.seed import crear_admin


def carga_de(cliente, area="Matemática", seccion="5to A"):
    areas = cliente.api("GET", "/api/areas").get_json()["areas"]
    a = next(x for x in areas if x["nombre"] == area)
    return next(s["carga_id"] for s in a["secciones"] if s["seccion"] == seccion)


def matriz(cliente, carga):
    return cliente.api("GET", f"/api/cargas/{carga}/matriz").get_json()


# ------------------------------------------------------------------ autenticación
def test_sin_sesion_redirige_y_api_da_401(app):
    c = app.test_client()
    r = c.get("/dashboard")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert c.get("/api/dashboard").status_code == 401
    assert c.get("/healthz").status_code == 200


def test_login_incorrecto_y_mensaje_generico(app):
    from tests.conftest import Cliente
    c = Cliente(app)
    r1 = c.login("docente", "mala")
    r2 = c.login("noexiste", "mala")
    assert r1.status_code == r2.status_code == 401
    assert "Usuario o contraseña incorrectos" in r1.get_data(as_text=True)


def test_bloqueo_por_intentos_fallidos(app):
    from tests.conftest import Cliente
    c = Cliente(app)
    for _ in range(5):
        assert c.login("docente", "mala").status_code == 401
    r = c.login("docente", "clave-segura-123")  # incluso con la clave correcta
    assert r.status_code == 429


def test_login_sin_csrf_rechazado(app):
    r = app.test_client().post("/login", data={"username": "docente", "password": "clave-segura-123"})
    assert r.status_code == 400


def test_logout_requiere_post_y_cierra_sesion(cliente):
    assert cliente.get("/logout").status_code == 405
    token = re.search(r'name="csrf_token" value="([^"]+)"', cliente.get("/dashboard").get_data(as_text=True)).group(1)
    assert cliente.c.post("/logout", data={"csrf_token": token}).status_code == 302
    assert cliente.get("/dashboard").status_code == 302


def test_redireccion_next_solo_interna(app):
    from tests.conftest import Cliente
    c = Cliente(app)
    c._refrescar_token()
    for malo in ("https://evil.example/", "//evil.example", "/\\evil.example"):
        r = c.c.post("/login", data={"username": "docente", "password": "clave-segura-123",
                                     "csrf_token": c.token, "next": malo})
        assert r.status_code == 302
        assert "evil" not in r.headers["Location"], malo
        c._refrescar_token()


# ------------------------------------------------------------------------- CSRF
def test_api_modificadora_sin_csrf_rechazada(cliente):
    carga = carga_de(cliente)
    r = cliente.c.put(f"/api/cargas/{carga}/calificaciones", json={"cambios": []})
    assert r.status_code == 400


# ---------------------------------------------------------------- calificaciones
def test_guardar_calificacion_recalcula(cliente):
    carga = carga_de(cliente)
    m = matriz(cliente, carga)
    fila = next(f for f in m["filas"] if f["nombre"] == "José Antonio Pérez")
    assert fila["promedio"] == 68.0 and fila["literal"] == "D"
    ev = {e["nombre"]: e["id"] for e in m["evaluaciones"]}
    cambios = [{"evaluacion_id": ev["Pruebas Escritas"], "inscripcion_id": fila["insc_id"], "puntaje": 27}]
    r = cliente.api("PUT", f"/api/cargas/{carga}/calificaciones", {"cambios": cambios})
    assert r.status_code == 200 and r.get_json()["guardados"] == 1
    fila2 = next(f for f in matriz(cliente, carga)["filas"] if f["insc_id"] == fila["insc_id"])
    assert fila2["promedio"] == 76.0 and fila2["literal"] == "C"  # 14+27+7+28


def test_puntaje_fuera_de_rango_no_guarda_nada(cliente):
    carga = carga_de(cliente)
    m = matriz(cliente, carga)
    ev = {e["nombre"]: e["id"] for e in m["evaluaciones"]}
    a, b = m["filas"][0], m["filas"][1]
    antes = [f["valores"] for f in m["filas"]]
    cambios = [
        {"evaluacion_id": ev["Pruebas Escritas"], "inscripcion_id": a["insc_id"], "puntaje": 5},      # válido
        {"evaluacion_id": ev["Pruebas Escritas"], "inscripcion_id": b["insc_id"], "puntaje": 31},     # > 30
    ]
    r = cliente.api("PUT", f"/api/cargas/{carga}/calificaciones", {"cambios": cambios})
    assert r.status_code == 422
    assert [f["valores"] for f in matriz(cliente, carga)["filas"]] == antes  # atómico


def test_valores_no_numericos_rechazados(cliente):
    carga = carga_de(cliente)
    m = matriz(cliente, carga)
    e, f = m["evaluaciones"][0]["id"], m["filas"][0]["insc_id"]
    for malo in ("abc", True, [1], {"a": 1}, float("nan"), -1):
        r = cliente.api("PUT", f"/api/cargas/{carga}/calificaciones",
                        {"cambios": [{"evaluacion_id": e, "inscripcion_id": f, "puntaje": malo}]}) \
            if malo == malo else cliente.c.put(
                f"/api/cargas/{carga}/calificaciones", data='{"cambios":[{"evaluacion_id":%d,"inscripcion_id":%d,"puntaje":NaN}]}' % (e, f),
                headers={"X-CSRF-Token": cliente.token, "Content-Type": "application/json"})
        assert r.status_code in (400, 422), (malo, r.status_code)


def test_puntaje_nulo_borra_la_nota(cliente):
    carga = carga_de(cliente)
    m = matriz(cliente, carga)
    e, f = m["evaluaciones"][0]["id"], m["filas"][0]["insc_id"]
    assert cliente.api("PUT", f"/api/cargas/{carga}/calificaciones",
                       {"cambios": [{"evaluacion_id": e, "inscripcion_id": f, "puntaje": None}]}).status_code == 200
    assert matriz(cliente, carga)["filas"][0]["valores"][str(e)] is None


def test_no_se_puede_calificar_estudiante_de_otra_seccion(cliente):
    carga_a = carga_de(cliente, seccion="5to A")
    carga_b = carga_de(cliente, seccion="5to B")
    ma, mb = matriz(cliente, carga_a), matriz(cliente, carga_b)
    r = cliente.api("PUT", f"/api/cargas/{carga_a}/calificaciones", {"cambios": [
        {"evaluacion_id": ma["evaluaciones"][0]["id"], "inscripcion_id": mb["filas"][0]["insc_id"], "puntaje": 1}]})
    assert r.status_code == 422
    r = cliente.api("PUT", f"/api/cargas/{carga_a}/calificaciones", {"cambios": [
        {"evaluacion_id": mb["evaluaciones"][0]["id"], "inscripcion_id": ma["filas"][0]["insc_id"], "puntaje": 1}]})
    assert r.status_code == 422


def test_periodo_cerrado_es_solo_lectura(cliente, app):
    carga = carga_de(cliente)
    m = matriz(cliente, carga)
    conn = connect(app.config)
    conn.execute("UPDATE periodos SET estado = 'cerrado' WHERE id = ?", (m["periodo"]["id"],))
    conn.commit(); conn.close()
    e, f = m["evaluaciones"][0]["id"], m["filas"][0]["insc_id"]
    r = cliente.api("PUT", f"/api/cargas/{carga}/calificaciones",
                    {"cambios": [{"evaluacion_id": e, "inscripcion_id": f, "puntaje": 1}]})
    assert r.status_code == 409
    assert cliente.api("DELETE", f"/api/evaluaciones/{e}").status_code == 409


# ------------------------------------------------------------------ autorización
def _segundo_docente(app):
    conn = connect(app.config)
    conn.execute("INSERT INTO usuarios (username, password_hash, nombre, cargo, nivel, activo, created_at) "
                 "VALUES (?,?,?,?,?,1,'2025-01-01T00:00:00Z')",
                 ("otro", security.hash_password("otra-clave-123"), "Otro Docente", "Docente", "Secundaria"))
    conn.commit(); conn.close()


def test_otro_docente_no_ve_ni_modifica_lo_ajeno(cliente, app):
    from tests.conftest import Cliente
    carga = carga_de(cliente)
    m = matriz(cliente, carga)
    _segundo_docente(app)
    otro = Cliente(app)
    assert otro.login("otro", "otra-clave-123").status_code == 302
    assert otro.api("GET", f"/api/cargas/{carga}/matriz").status_code == 404
    assert otro.api("GET", "/api/estudiantes/1").status_code == 404
    assert otro.get("/estudiantes/1").status_code == 404
    e, f = m["evaluaciones"][0]["id"], m["filas"][0]["insc_id"]
    assert otro.api("PUT", f"/api/cargas/{carga}/calificaciones",
                    {"cambios": [{"evaluacion_id": e, "inscripcion_id": f, "puntaje": 1}]}).status_code == 404
    assert otro.api("DELETE", f"/api/evaluaciones/{e}").status_code == 404
    assert otro.api("POST", f"/api/estudiantes/{f}/observaciones",
                    {"tipo": "fortaleza", "descripcion": "x"}).status_code == 404
    assert otro.api("GET", "/api/dashboard").get_json()["vacio"] is True


# ------------------------------------------------------------------ evaluaciones
def test_crear_evaluacion_respeta_el_100_por_ciento(cliente):
    carga = carga_de(cliente)
    m = matriz(cliente, carga)
    cuerpo = {"carga_ids": [carga], "periodo_id": m["periodo"]["id"], "nombre": "Extra", "tipo": "prueba_escrita",
              "peso": 10, "max_puntaje": 50}
    r = cliente.api("POST", "/api/evaluaciones", cuerpo)  # ya suma 100 %
    assert r.status_code == 422 and "100" in r.get_json()["error"]


def test_crear_y_eliminar_evaluacion(cliente):
    carga = carga_de(cliente, "Matemática", "5to B")
    m = matriz(cliente, carga)
    ev = m["evaluaciones"][-1]
    assert cliente.api("DELETE", f"/api/evaluaciones/{ev['id']}").status_code == 200
    bal = cliente.api("GET", f"/api/cargas/{carga}/periodos/{m['periodo']['id']}/balance").get_json()
    assert bal["disponible"] == ev["peso"]
    cuerpo = {"carga_ids": [carga], "periodo_id": m["periodo"]["id"], "nombre": "Nueva", "tipo": "proyecto_integrador",
              "peso": ev["peso"], "max_puntaje": 100, "fecha": "2025-11-01"}
    r = cliente.api("POST", "/api/evaluaciones", cuerpo)
    assert r.status_code == 201
    # sin calificaciones todavía: promedio ignora la evaluación sin notas
    assert matriz(cliente, carga)["resumen"]["pendientes"] == len(m["filas"])


def test_validacion_de_evaluacion(cliente):
    carga = carga_de(cliente, "Inglés", "5to A")
    pid = matriz(cliente, carga)["periodo"]["id"]
    base = {"carga_ids": [carga], "periodo_id": pid, "nombre": "X", "tipo": "prueba_escrita", "peso": 1}
    malos = [
        {**base, "nombre": "  "}, {**base, "tipo": "inventado"}, {**base, "peso": 0}, {**base, "peso": -5},
        {**base, "peso": "10"}, {**base, "max_puntaje": 0}, {**base, "fecha": "31/12/2025"},
        {**base, "carga_ids": []}, {**base, "carga_ids": [999999]}, {**base, "periodo_id": 999999},
    ]
    for cuerpo in malos:
        assert cliente.api("POST", "/api/evaluaciones", cuerpo).status_code in (404, 422), cuerpo
    assert cliente.c.post("/api/evaluaciones", data="no-json",
                          headers={"X-CSRF-Token": cliente.token}).status_code == 422


# ---------------------------------------------------------------- observaciones
def test_observacion_actualiza_estado_y_escapa_html(cliente):
    insc = cliente.api("GET", "/api/estudiantes/1").get_json()["insc"]["id"]
    r = cliente.api("POST", f"/api/estudiantes/{insc}/observaciones",
                    {"tipo": "estrategia_recuperacion", "aspecto": "Mat", "descripcion": "<script>alert(1)</script>"})
    assert r.status_code == 201
    html = cliente.get(f"/estudiantes/{insc}").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert cliente.api("POST", f"/api/estudiantes/{insc}/observaciones", {"tipo": "x", "descripcion": "y"}).status_code == 422
    assert cliente.api("POST", f"/api/estudiantes/{insc}/observaciones", {"tipo": "fortaleza", "descripcion": " "}).status_code == 422


# ----------------------------------------------------------------- contexto/cuenta
def test_cambio_de_periodo_y_next_seguro(cliente):
    r = cliente.get("/contexto?periodo=2&next=https://evil.example")
    assert r.status_code == 302 and "evil" not in r.headers["Location"]
    assert cliente.get("/dashboard").status_code == 200
    # un período de otro año o inexistente se ignora
    assert cliente.get("/contexto?periodo=99999&next=/dashboard").status_code == 302
    assert cliente.get("/dashboard").status_code == 200


def test_cambiar_password(cliente, app):
    token = re.search(r'name="csrf_token" value="([^"]+)"', cliente.get("/configuracion").get_data(as_text=True)).group(1)
    def enviar(actual, nueva, conf):
        return cliente.c.post("/configuracion", data={"actual": actual, "nueva": nueva, "confirmar": conf, "csrf_token": token})
    assert "no es correcta" in enviar("mala", "nueva-clave-123", "nueva-clave-123").get_data(as_text=True)
    assert "al menos 8" in enviar("clave-segura-123", "corta", "corta").get_data(as_text=True)
    assert "no coinciden" in enviar("clave-segura-123", "nueva-clave-123", "otra-cosa-123").get_data(as_text=True)
    assert "actualizada" in enviar("clave-segura-123", "nueva-clave-123", "nueva-clave-123").get_data(as_text=True)
    from tests.conftest import Cliente
    assert Cliente(app).login("docente", "nueva-clave-123").status_code == 302


def test_cabeceras_de_seguridad(cliente):
    r = cliente.get("/dashboard")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store"


def test_error_404_y_405_amigables(cliente):
    assert "No encontramos" in cliente.get("/no-existe").get_data(as_text=True)
    assert cliente.api("GET", "/api/cargas/999999/matriz").status_code == 404


def test_arranque_en_produccion_exige_secret_key(monkeypatch, tmp_path):
    import pytest
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        create_app({"SQLITE_PATH": str(tmp_path / "x.db")})


def test_admin_solo_se_crea_si_no_hay_usuarios(tmp_path):
    app = create_app({"SQLITE_PATH": str(tmp_path / "y.db"), "ADMIN_USERNAME": "a", "ADMIN_PASSWORD": "12345678",
                      "SEED_DEMO_DATA": False})
    conn = connect(app.config)
    assert crear_admin(conn, "b", "12345678", "B") is False
    assert conn.scalar("SELECT COUNT(*) FROM usuarios") == 1
    conn.close()


def test_x_forwarded_for_falsificado_no_evita_el_bloqueo(app):
    from tests.conftest import Cliente
    c = Cliente(app)
    c._refrescar_token()
    for n in range(5):
        c.c.post("/login", data={"username": "docente", "password": "mala", "csrf_token": c.token},
                 headers={"X-Forwarded-For": f"10.0.0.{n}"})
    r = c.c.post("/login", data={"username": "docente", "password": "clave-segura-123", "csrf_token": c.token},
                 headers={"X-Forwarded-For": "203.0.113.99"})
    assert r.status_code == 429
