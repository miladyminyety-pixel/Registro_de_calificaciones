"""Importación de estudiantes desde CSV o Excel (.xlsx).

Flujo: ``leer_archivo`` (bytes -> filas crudas) -> ``validar`` (filas -> válidas/errores,
sin tocar la base de datos salvo para consultar) -> ``aplicar`` (escribe todo en una
sola transacción). La confirmación vuelve a validar, así que nada se fía de la vista previa.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata

from .db import Conn, utcnow
from .errors import invalid

MAX_BYTES = 2 * 1024 * 1024
MAX_FILAS = 2000

COLUMNAS = ["matricula", "rne", "nombres", "apellidos", "grado", "seccion", "condicion"]
OBLIGATORIAS = ["matricula", "nombres", "apellidos", "grado", "seccion"]
_ALIAS = {
    "matricula": {"matricula", "mat", "codigo", "numeromatricula", "nmatricula"},
    "rne": {"rne"},
    "nombres": {"nombres", "nombre", "primernombre"},
    "apellidos": {"apellidos", "apellido"},
    "grado": {"grado", "curso"},
    "seccion": {"seccion", "letra", "grupo"},
    "condicion": {"condicion"},
}
_ETIQUETA = {"matricula": "matrícula", "nombres": "nombres", "apellidos": "apellidos",
             "grado": "grado", "seccion": "sección", "rne": "RNE", "condicion": "condición"}
ORDINALES = {1: "1ro", 2: "2do", 3: "3ro", 4: "4to", 5: "5to", 6: "6to"}
NIVELES = {"Secundaria": "Secundaria General", "Primaria": "Primaria"}
_GRADO_RE = re.compile(r"^(\d{1,2})\s*(?:ro|do|to|er|mo|vo|º|°|\.)?\s*(?:primaria|secundaria|basica)?\s*$")
_SECCION_RE = re.compile(r"^[A-Z0-9]{1,3}$")


def _sin_acentos(texto: str) -> str:
    base = unicodedata.normalize("NFD", texto)
    return "".join(c for c in base if unicodedata.category(c) != "Mn")


def _clave(encabezado: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _sin_acentos(str(encabezado or "")).lower())


def _celda(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():  # Excel guarda 123 como 123.0
        valor = int(valor)
    return re.sub(r"\s+", " ", str(valor)).strip()


# ----------------------------------------------------------------------- lectura
def _decodificar(datos: bytes) -> str:
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            return datos.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return datos.decode("latin-1")


def _filas_csv(datos: bytes) -> list[list[str]]:
    texto = _decodificar(datos)
    muestra = texto[:4096]
    delimitador = max(",;\t", key=muestra.count)
    return [list(f) for f in csv.reader(io.StringIO(texto), delimiter=delimitador)]


def _filas_xlsx(datos: bytes) -> list[list[str]]:
    if not datos.startswith(b"PK"):
        raise invalid("El archivo no es un Excel (.xlsx) válido", "archivo")
    try:
        from openpyxl import load_workbook
        libro = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    except Exception:
        raise invalid("No se pudo abrir el Excel. Guárdalo como .xlsx o .csv e inténtalo de nuevo", "archivo")
    try:
        hoja = libro.worksheets[0]
        filas = []
        for n, fila in enumerate(hoja.iter_rows(values_only=True)):
            if n > MAX_FILAS + 50:
                break
            filas.append(list(fila))
        return filas
    finally:
        libro.close()


def leer_archivo(nombre: str, datos: bytes) -> list[dict]:
    """Devuelve las filas como dict {columna: texto, '_fila': n° de fila en el archivo}."""
    if not datos:
        raise invalid("El archivo está vacío", "archivo")
    if len(datos) > MAX_BYTES:
        raise invalid("El archivo supera los 2 MB", "archivo")
    extension = (nombre or "").lower().rsplit(".", 1)[-1] if "." in (nombre or "") else ""
    if extension == "csv" or extension == "txt":
        crudas = _filas_csv(datos)
    elif extension == "xlsx":
        crudas = _filas_xlsx(datos)
    else:
        raise invalid("Formato no admitido: sube un archivo .csv o .xlsx", "archivo")

    crudas = [f for f in crudas if any(_celda(c) for c in f)]
    if not crudas:
        raise invalid("El archivo no tiene datos", "archivo")

    mapa: dict[int, str] = {}
    for indice, encabezado in enumerate(crudas[0]):
        k = _clave(encabezado)
        for columna, alias in _ALIAS.items():
            if k in alias and columna not in mapa.values():
                mapa[indice] = columna
    faltan = [_ETIQUETA[c] for c in OBLIGATORIAS if c not in mapa.values()]
    if faltan:
        raise invalid("Faltan columnas obligatorias en la primera fila: " + ", ".join(faltan) +
                      ". Descarga la plantilla para ver el formato.", "archivo")

    cuerpo = crudas[1:]
    if len(cuerpo) > MAX_FILAS:
        raise invalid(f"El archivo tiene más de {MAX_FILAS} estudiantes; divídelo en partes", "archivo")
    filas = []
    for n, fila in enumerate(cuerpo, start=2):
        registro = {c: "" for c in COLUMNAS}
        for indice, columna in mapa.items():
            if indice < len(fila):
                registro[columna] = _celda(fila[indice])
        registro["_fila"] = n
        filas.append(registro)
    return filas


# -------------------------------------------------------------------- validación
def normalizar_grado(valor: str) -> str | None:
    m = _GRADO_RE.match(_sin_acentos(valor or "").lower().strip())
    if not m or not 1 <= int(m.group(1)) <= 6:
        return None
    return ORDINALES[int(m.group(1))]


def validar(db: Conn, filas: list[dict], anio_id: int, centro_id: int | None, nivel: str) -> dict:
    """Valida las filas. No escribe nada."""
    errores: list[dict] = []
    advertencias: list[dict] = []
    validas: list[dict] = []
    vistas: dict[str, dict] = {}

    existentes = {}
    matriculas = [f["matricula"] for f in filas if f.get("matricula")]
    for i in range(0, len(matriculas), 400):
        trozo = matriculas[i:i + 400]
        for r in db.query(
            f"SELECT id, matricula, nombres, apellidos FROM estudiantes WHERE matricula IN ({','.join('?' * len(trozo))})",
            trozo,
        ):
            existentes[r["matricula"]] = r

    inscritos = {}
    if existentes:
        ids = [e["id"] for e in existentes.values()]
        for i in range(0, len(ids), 400):
            trozo = ids[i:i + 400]
            for r in db.query(
                f"""SELECT i.estudiante_id, s.grado, s.letra, s.centro_id FROM inscripciones i
                    JOIN secciones s ON s.id = i.seccion_id
                    WHERE s.anio_id = ? AND i.estudiante_id IN ({','.join('?' * len(trozo))})""",
                [anio_id] + trozo,
            ):
                inscritos[r["estudiante_id"]] = r

    def error(fila, campo, mensaje):
        errores.append({"fila": fila["_fila"], "campo": campo, "mensaje": mensaje})

    for f in filas:
        malo = False
        matricula, nombres, apellidos = f["matricula"], f["nombres"], f["apellidos"]
        if not matricula:
            error(f, "matrícula", "Falta la matrícula"); malo = True
        elif len(matricula) > 40 or not re.match(r"^[\w.\-/ ]+$", matricula):
            error(f, "matrícula", "Matrícula no válida (letras, números, guiones; máx. 40)"); malo = True
        if not nombres:
            error(f, "nombres", "Faltan los nombres"); malo = True
        elif len(nombres) > 80:
            error(f, "nombres", "Nombres demasiado largos (máx. 80)"); malo = True
        if not apellidos:
            error(f, "apellidos", "Faltan los apellidos"); malo = True
        elif len(apellidos) > 80:
            error(f, "apellidos", "Apellidos demasiado largos (máx. 80)"); malo = True
        if len(f["rne"]) > 40:
            error(f, "RNE", "RNE demasiado largo (máx. 40)"); malo = True
        if len(f["condicion"]) > 30:
            error(f, "condición", "Condición demasiado larga (máx. 30)"); malo = True
        grado = normalizar_grado(f["grado"])
        if grado is None:
            error(f, "grado", f"Grado no reconocido: «{f['grado']}» (use 1 a 6, por ejemplo 5 o 5to)"); malo = True
        letra = f["seccion"].upper()
        if not _SECCION_RE.match(letra):
            error(f, "sección", f"Sección no válida: «{f['seccion']}» (use una letra, por ejemplo A)"); malo = True
        if malo:
            continue

        anterior = vistas.get(matricula.lower())
        if anterior:
            error(f, "matrícula", f"Matrícula repetida (ya aparece en la fila {anterior['_fila']})")
            continue

        registro = {"_fila": f["_fila"], "matricula": matricula, "rne": f["rne"] or None, "nombres": nombres,
                    "apellidos": apellidos, "grado": grado, "seccion": letra,
                    "condicion": f["condicion"] or "Regular", "estado": "nuevo"}
        existente = existentes.get(matricula)
        if existente:
            if (existente["nombres"].lower(), existente["apellidos"].lower()) != (nombres.lower(), apellidos.lower()):
                advertencias.append({"fila": f["_fila"], "mensaje":
                    f"La matrícula {matricula} ya existe como «{existente['nombres']} {existente['apellidos']}»; "
                    "se conserva ese nombre."})
            actual = inscritos.get(existente["id"])
            if actual and (actual["grado"], actual["letra"], actual["centro_id"]) == (grado, letra, centro_id):
                registro["estado"] = "ya_inscrito"
            elif actual:
                error(f, "sección", f"Ya está inscrito en {actual['grado']} {actual['letra']} este año lectivo")
                continue
            else:
                registro["estado"] = "existente"
            registro["estudiante_id"] = existente["id"]
        vistas[matricula.lower()] = registro
        validas.append(registro)

    secciones = sorted({(v["grado"], v["seccion"]) for v in validas})
    return {
        "validas": validas, "errores": errores, "advertencias": advertencias,
        "secciones": [f"{g} {s}" for g, s in secciones],
        "resumen": {
            "total": len(filas), "nuevos": sum(v["estado"] == "nuevo" for v in validas),
            "existentes": sum(v["estado"] == "existente" for v in validas),
            "ya_inscritos": sum(v["estado"] == "ya_inscrito" for v in validas),
            "con_errores": len({e["fila"] for e in errores}),
        },
    }


# ---------------------------------------------------------------------- escritura
def _centro(db: Conn, nombre: str, regional: str | None, distrito: str | None) -> int:
    fila = db.one("SELECT id FROM centros WHERE LOWER(nombre) = LOWER(?)", (nombre,))
    if fila:
        return fila["id"]
    return db.insert("INSERT INTO centros (nombre, regional, distrito) VALUES (?,?,?)", (nombre, regional, distrito))


def aplicar(db: Conn, user: dict, anio_id: int, centro: dict, nivel: str, area_ids: list[int],
            validas: list[dict], ser_tutor: bool) -> dict:
    """Escribe secciones, estudiantes, inscripciones y cargas. Todo o nada."""
    if not validas:
        raise invalid("No hay estudiantes válidos para importar")
    ahora = utcnow()
    resumen = {"estudiantes_nuevos": 0, "inscripciones": 0, "secciones_nuevas": 0, "cargas_nuevas": 0,
               "cargas_omitidas": []}
    try:
        centro_id = _centro(db, centro["nombre"], centro.get("regional"), centro.get("distrito"))
        secciones: dict[tuple[str, str], int] = {}
        for grado, letra in sorted({(v["grado"], v["seccion"]) for v in validas}):
            fila = db.one(
                "SELECT id, tutor_id FROM secciones WHERE anio_id = ? AND centro_id = ? AND grado = ? AND letra = ?",
                (anio_id, centro_id, grado, letra))
            if fila:
                sid = fila["id"]
                if ser_tutor and fila["tutor_id"] is None:
                    db.execute("UPDATE secciones SET tutor_id = ? WHERE id = ?", (user["id"], sid))
            else:
                sid = db.insert(
                    "INSERT INTO secciones (anio_id, centro_id, grado, grado_nombre, letra, modalidad, tutor_id) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (anio_id, centro_id, grado, f"{grado} {nivel}", letra, NIVELES[nivel],
                     user["id"] if ser_tutor else None))
                resumen["secciones_nuevas"] += 1
            secciones[(grado, letra)] = sid

        for v in validas:
            sid = secciones[(v["grado"], v["seccion"])]
            if v["estado"] == "ya_inscrito":
                continue
            est_id = v.get("estudiante_id")
            if est_id is None:
                est_id = db.insert(
                    "INSERT INTO estudiantes (matricula, rne, nombres, apellidos, activo, created_at) VALUES (?,?,?,?,1,?)",
                    (v["matricula"], v["rne"], v["nombres"], v["apellidos"], ahora))
                resumen["estudiantes_nuevos"] += 1
            db.execute(
                "INSERT INTO inscripciones (estudiante_id, seccion_id, condicion) VALUES (?,?,?)",
                (est_id, sid, v["condicion"]))
            resumen["inscripciones"] += 1

        nombres_area = {a["id"]: a["nombre"] for a in db.query("SELECT id, nombre FROM areas")}
        for (grado, letra), sid in secciones.items():
            for area_id in area_ids:
                existente = db.one("SELECT id, docente_id FROM cargas WHERE seccion_id = ? AND area_id = ?", (sid, area_id))
                if existente is None:
                    db.insert("INSERT INTO cargas (docente_id, seccion_id, area_id) VALUES (?,?,?)",
                              (user["id"], sid, area_id))
                    resumen["cargas_nuevas"] += 1
                elif existente["docente_id"] != user["id"]:
                    resumen["cargas_omitidas"].append(f"{nombres_area[area_id]} en {grado} {letra} (ya la imparte otro docente)")
        db.commit()
    except Exception:
        db.rollback()
        raise
    resumen["secciones"] = [f"{g} {l}" for g, l in sorted(secciones)]
    return resumen


# ---------------------------------------------------------------------- plantilla
EJEMPLOS = [
    ["MAT-2026-0001", "10492801", "María", "Fernández", "5to", "A", "Regular"],
    ["MAT-2026-0002", "10492802", "José Antonio", "Pérez", "5to", "A", "Regular"],
    ["MAT-2026-0003", "", "Ana", "Martínez", "5to", "B", "Repitente"],
]


def plantilla_csv() -> bytes:
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(COLUMNAS)
    escritor.writerows(EJEMPLOS)
    return ("﻿" + salida.getvalue()).encode("utf-8")  # BOM: Excel abre bien los acentos


def plantilla_xlsx() -> bytes:
    from openpyxl import Workbook
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Estudiantes"
    hoja.append(COLUMNAS)
    for fila in EJEMPLOS:
        hoja.append(fila)
    for col, ancho in zip("ABCDEFG", (18, 14, 22, 22, 10, 10, 14)):
        hoja.column_dimensions[col].width = ancho
    from openpyxl.styles import Font
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for fila in hoja.iter_rows(min_row=2, max_col=1):
        fila[0].number_format = "@"  # matrícula como texto
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
