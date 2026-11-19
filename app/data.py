"""Carga de datos y contexto (año lectivo / período) compartidos por las vistas."""
from __future__ import annotations

from collections import defaultdict

from . import grading
from .errors import not_found

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def placeholders(n: int) -> str:
    return ",".join("?" * n)


def fecha_corta(iso: str | None) -> str:
    """'2025-10-14' o '2025-10-14T10:00:00Z' -> '14 Oct 2025'."""
    if not iso:
        return ""
    try:
        y, m, d = int(iso[0:4]), int(iso[5:7]), int(iso[8:10])
        return f"{d} {MESES[m - 1]} {y}"
    except (ValueError, IndexError):
        return iso


def iniciales(nombres: str, apellidos: str) -> str:
    a = (nombres or " ")[0]
    b = (apellidos or " ")[0]
    return (a + b).upper().strip()


# ---------------------------------------------------------------------- contexto
def resolver_contexto(db, anio_id: int | None = None, periodo_id: int | None = None) -> dict:
    """Año lectivo y período activos de la sesión (con valores por defecto)."""
    anios = db.query("SELECT id, nombre, activo FROM anios_lectivos ORDER BY nombre DESC")
    anio = next((a for a in anios if a["id"] == anio_id), None)
    if anio is None:
        anio = next((a for a in anios if a["activo"]), anios[0] if anios else None)
    periodos = []
    periodo = None
    if anio:
        periodos = db.query(
            "SELECT id, numero, nombre, estado, meta FROM periodos WHERE anio_id = ? ORDER BY numero",
            (anio["id"],),
        )
        periodo = next((p for p in periodos if p["id"] == periodo_id), None)
        if periodo is None:
            periodo = next((p for p in periodos if p["estado"] == "en_curso"), periodos[0] if periodos else None)
    return {"anios": anios, "anio": anio, "periodos": periodos, "periodo": periodo}


# ------------------------------------------------------------------------ cargas
_CARGA_SQL = """
    SELECT c.id, c.docente_id, c.area_id, c.seccion_id,
           a.nombre AS area, a.nombre_largo AS area_larga, a.categoria, a.icono, a.estilo, a.orden,
           s.grado, s.letra, s.grado_nombre, s.modalidad, s.anio_id, s.tutor_id
    FROM cargas c
    JOIN areas a ON a.id = c.area_id
    JOIN secciones s ON s.id = c.seccion_id
"""


def _decorar_carga(c: dict) -> dict:
    c["seccion"] = f"{c['grado']} {c['letra']}"
    c["area_titulo"] = c["area_larga"] or c["area"]
    return c


def cargas_docente(db, user_id: int, anio_id: int, seccion_id: int | None = None,
                   area_id: int | None = None) -> list[dict]:
    sql = _CARGA_SQL + " WHERE c.docente_id = ? AND s.anio_id = ?"
    params: list = [user_id, anio_id]
    if seccion_id:
        sql += " AND c.seccion_id = ?"
        params.append(seccion_id)
    if area_id:
        sql += " AND c.area_id = ?"
        params.append(area_id)
    sql += " ORDER BY a.orden, a.nombre, s.grado, s.letra"
    return [_decorar_carga(c) for c in db.query(sql, params)]


def carga_propia(db, user_id: int, carga_id: int) -> dict:
    """Carga que pertenece al docente; 404 si no existe o es de otra persona."""
    fila = db.one(_CARGA_SQL + " WHERE c.id = ? AND c.docente_id = ?", (carga_id, user_id))
    if fila is None:
        raise not_found("Carga académica no encontrada")
    return _decorar_carga(fila)


def secciones_docente(db, user_id: int, anio_id: int) -> list[dict]:
    filas = db.query(
        """
        SELECT DISTINCT s.id, s.grado, s.letra, s.grado_nombre, s.modalidad
        FROM secciones s
        WHERE s.anio_id = ?
          AND (s.tutor_id = ? OR EXISTS (SELECT 1 FROM cargas c WHERE c.seccion_id = s.id AND c.docente_id = ?))
        ORDER BY s.grado, s.letra
        """,
        (anio_id, user_id, user_id),
    )
    for s in filas:
        s["seccion"] = f"{s['grado']} {s['letra']}"
    return filas


def inscripciones(db, seccion_ids: list[int]) -> list[dict]:
    if not seccion_ids:
        return []
    filas = db.query(
        f"""
        SELECT i.id, i.seccion_id, i.condicion, i.estado_acompanamiento,
               e.id AS estudiante_id, e.matricula, e.rne, e.nombres, e.apellidos
        FROM inscripciones i
        JOIN estudiantes e ON e.id = i.estudiante_id
        WHERE i.seccion_id IN ({placeholders(len(seccion_ids))}) AND e.activo = 1
        ORDER BY e.apellidos, e.nombres, e.id
        """,
        seccion_ids,
    )
    for f in filas:
        f["nombre"] = f"{f['nombres']} {f['apellidos']}"
        f["iniciales"] = iniciales(f["nombres"], f["apellidos"])
    return filas


# ------------------------------------------------------------------------- datos
class Datos:
    """Evaluaciones, notas y estudiantes de un conjunto de cargas (cargados en bloque)."""

    def __init__(self, db, cargas: list[dict], periodo_ids: list[int]):
        self.cargas = {c["id"]: c for c in cargas}
        self.inscs: dict[int, list[dict]] = defaultdict(list)
        for i in inscripciones(db, sorted({c["seccion_id"] for c in cargas})):
            self.inscs[i["seccion_id"]].append(i)

        self.evals: dict[tuple[int, int], list[dict]] = defaultdict(list)
        self.puntajes: dict[tuple[int, int], float | None] = {}
        carga_ids = list(self.cargas)
        if carga_ids and periodo_ids:
            filas = db.query(
                f"""
                SELECT id, carga_id, periodo_id, nombre, tipo, competencia, fecha, max_puntaje, peso, indicadores
                FROM evaluaciones
                WHERE carga_id IN ({placeholders(len(carga_ids))})
                  AND periodo_id IN ({placeholders(len(periodo_ids))})
                ORDER BY fecha, id
                """,
                carga_ids + list(periodo_ids),
            )
            for e in filas:
                self.evals[(e["carga_id"], e["periodo_id"])].append(e)
            eval_ids = [e["id"] for e in filas]
            if eval_ids:
                for p in db.query(
                    f"SELECT evaluacion_id, inscripcion_id, puntaje FROM calificaciones "
                    f"WHERE evaluacion_id IN ({placeholders(len(eval_ids))})",
                    eval_ids,
                ):
                    self.puntajes[(p["evaluacion_id"], p["inscripcion_id"])] = p["puntaje"]

    def estudiantes_de(self, carga_id: int) -> list[dict]:
        return self.inscs[self.cargas[carga_id]["seccion_id"]]

    def evaluaciones_de(self, carga_id: int, periodo_id: int) -> list[dict]:
        return self.evals[(carga_id, periodo_id)]

    def resultado(self, carga_id: int, periodo_id: int, insc_id: int) -> dict:
        items = [
            (self.puntajes.get((e["id"], insc_id)), e["max_puntaje"], e["peso"])
            for e in self.evals[(carga_id, periodo_id)]
        ]
        return grading.promedio_ponderado(items)

    def promedios(self, carga_id: int, periodo_id: int) -> dict[int, float]:
        """insc_id -> promedio del período (solo estudiantes con algo calificado)."""
        salida = {}
        for insc in self.estudiantes_de(carga_id):
            p = self.resultado(carga_id, periodo_id, insc["id"])["promedio"]
            if p is not None:
                salida[insc["id"]] = p
        return salida

    def celdas(self, carga_id: int, periodo_id: int) -> tuple[int, int]:
        """(calificadas, esperadas) = celdas de la matriz estudiante x evaluación."""
        estudiantes = self.estudiantes_de(carga_id)
        evals = self.evals[(carga_id, periodo_id)]
        hechas = sum(
            1 for e in evals for i in estudiantes if self.puntajes.get((e["id"], i["id"])) is not None
        )
        return hechas, len(evals) * len(estudiantes)


# ----------------------------------------------------------------------- acceso
def inscripcion_accesible(db, user_id: int, insc_id: int) -> dict:
    """Inscripción visible para el docente (tiene carga en la sección o es su tutor)."""
    fila = db.one(
        """
        SELECT i.id, i.seccion_id, i.condicion, i.estado_acompanamiento,
               e.id AS estudiante_id, e.matricula, e.rne, e.nombres, e.apellidos,
               s.grado, s.letra, s.grado_nombre, s.modalidad, s.anio_id, s.tutor_id, s.centro_id
        FROM inscripciones i
        JOIN estudiantes e ON e.id = i.estudiante_id
        JOIN secciones s ON s.id = i.seccion_id
        WHERE i.id = ?
          AND (s.tutor_id = ? OR EXISTS (SELECT 1 FROM cargas c WHERE c.seccion_id = s.id AND c.docente_id = ?))
        """,
        (insc_id, user_id, user_id),
    )
    if fila is None:
        raise not_found("Estudiante no encontrado")
    fila["nombre"] = f"{fila['nombres']} {fila['apellidos']}"
    fila["iniciales"] = iniciales(fila["nombres"], fila["apellidos"])
    fila["seccion"] = f"{fila['grado']} {fila['letra']}"
    return fila


def cargas_visibles_en_seccion(db, user_id: int, seccion_id: int, tutor_id: int | None) -> list[dict]:
    """Cargas de la sección que el docente puede ver: las suyas, o todas si es el tutor."""
    sql = _CARGA_SQL + " WHERE c.seccion_id = ?"
    params: list = [seccion_id]
    if tutor_id != user_id:
        sql += " AND c.docente_id = ?"
        params.append(user_id)
    sql += " ORDER BY a.orden, a.nombre"
    return [_decorar_carga(c) for c in db.query(sql, params)]
