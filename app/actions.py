"""Operaciones que modifican datos. Validan todo antes de escribir y son atómicas."""
from __future__ import annotations

import math
from datetime import date

from . import grading
from .data import Datos, carga_propia, fecha_corta, inscripcion_accesible
from .db import utcnow
from .errors import ApiError, invalid
from .security import MIN_PASSWORD, hash_password, verify_password

MAX_CAMBIOS = 5000


def _numero(valor, campo: str, minimo: float | None = None, maximo: float | None = None,
            exclusivo_min: bool = False) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise invalid("Debe ser un número válido", campo)
    if minimo is not None and (valor <= minimo if exclusivo_min else valor < minimo):
        raise invalid(f"Debe ser {'mayor que' if exclusivo_min else 'al menos'} {minimo:g}", campo)
    if maximo is not None and valor > maximo:
        raise invalid(f"No puede superar {maximo:g}", campo)
    return float(valor)


def _texto(valor, campo: str, maximo: int, obligatorio: bool = False) -> str | None:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        if obligatorio:
            raise invalid("Este campo es obligatorio", campo)
        return None
    if not isinstance(valor, str):
        raise invalid("Debe ser texto", campo)
    valor = valor.strip()
    if len(valor) > maximo:
        raise invalid(f"Máximo {maximo} caracteres", campo)
    return valor


def _periodo_abierto(db, periodo_id: int, anio_id: int | None = None) -> dict:
    periodo = db.one("SELECT id, anio_id, nombre, estado FROM periodos WHERE id = ?", (periodo_id,))
    if periodo is None or (anio_id is not None and periodo["anio_id"] != anio_id):
        raise ApiError(404, "Período no encontrado")
    if periodo["estado"] == "cerrado":
        raise ApiError(409, f"El {periodo['nombre']} está cerrado y no admite cambios")
    return periodo


# ------------------------------------------------------------------ calificaciones
def guardar_calificaciones(db, user: dict, carga_id: int, cambios) -> dict:
    carga = carga_propia(db, user["id"], carga_id)
    if not isinstance(cambios, list) or not cambios:
        raise invalid("No hay cambios que guardar", "cambios")
    if len(cambios) > MAX_CAMBIOS:
        raise invalid(f"Demasiados cambios en una sola petición (máximo {MAX_CAMBIOS})", "cambios")

    evals = {
        e["id"]: e for e in db.query(
            "SELECT e.id, e.max_puntaje, e.periodo_id, p.estado, p.nombre AS periodo "
            "FROM evaluaciones e JOIN periodos p ON p.id = e.periodo_id WHERE e.carga_id = ?",
            (carga_id,),
        )
    }
    validas = {r["id"] for r in db.query(
        "SELECT id FROM inscripciones WHERE seccion_id = ?", (carga["seccion_id"],))}

    errores, filas = [], {}
    for n, cambio in enumerate(cambios):
        if not isinstance(cambio, dict):
            errores.append({"indice": n, "error": "Formato inválido"})
            continue
        eval_id, insc_id, puntaje = cambio.get("evaluacion_id"), cambio.get("inscripcion_id"), cambio.get("puntaje")
        ev = evals.get(eval_id) if isinstance(eval_id, int) and not isinstance(eval_id, bool) else None
        if ev is None:
            errores.append({"indice": n, "error": "Evaluación no pertenece a esta carga"})
            continue
        if not (isinstance(insc_id, int) and not isinstance(insc_id, bool)) or insc_id not in validas:
            errores.append({"indice": n, "error": "Estudiante no pertenece a esta sección"})
            continue
        if ev["estado"] == "cerrado":
            raise ApiError(409, f"El {ev['periodo']} está cerrado y no admite cambios")
        if puntaje is not None:
            try:
                puntaje = _numero(puntaje, "puntaje", 0, ev["max_puntaje"])
            except ApiError as exc:
                errores.append({"indice": n, "evaluacion_id": eval_id, "inscripcion_id": insc_id,
                                "error": f"{exc.message} (máximo {ev['max_puntaje']:g})"})
                continue
        filas[(eval_id, insc_id)] = puntaje
    if errores:
        raise invalid("Hay calificaciones no válidas; no se guardó ninguna", details=errores[:20])

    ahora = utcnow()
    db.executemany(
        """
        INSERT INTO calificaciones (evaluacion_id, inscripcion_id, puntaje, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (evaluacion_id, inscripcion_id)
        DO UPDATE SET puntaje = excluded.puntaje, updated_by = excluded.updated_by,
                      updated_at = excluded.updated_at
        """,
        [(e, i, p, user["id"], ahora) for (e, i), p in filas.items()],
    )
    db.commit()

    periodos = sorted({evals[e]["periodo_id"] for (e, _i) in filas})
    datos = Datos(db, [carga], periodos)
    resultados = []
    for insc_id in sorted({i for (_e, i) in filas}):
        for pid in periodos:
            r = datos.resultado(carga_id, pid, insc_id)
            resultados.append({"inscripcion_id": insc_id, "periodo_id": pid,
                               "promedio": r["promedio"], "literal": grading.literal_de(r["promedio"])})
    return {"guardados": len(filas), "resultados": resultados}


# -------------------------------------------------------------------- evaluaciones
def balance(db, user: dict, carga_id: int, periodo_id: int) -> dict:
    carga = carga_propia(db, user["id"], carga_id)
    periodo = db.one("SELECT id, anio_id, nombre, estado FROM periodos WHERE id = ?", (periodo_id,))
    if periodo is None or periodo["anio_id"] != carga["anio_id"]:
        raise ApiError(404, "Período no encontrado")
    evals = db.query(
        "SELECT id, nombre, tipo, fecha, max_puntaje, peso FROM evaluaciones "
        "WHERE carga_id = ? AND periodo_id = ? ORDER BY fecha, id",
        (carga_id, periodo_id),
    )
    for e in evals:
        info = grading.TIPOS_EVALUACION.get(e["tipo"], {})
        e["tipo_label"] = info.get("label", e["tipo"])
        e["icono"] = info.get("icono", "assignment")
        e["fecha_corta"] = fecha_corta(e["fecha"])
    asignado = sum(e["peso"] for e in evals)
    return {
        "carga_id": carga_id, "seccion": carga["seccion"], "area": carga["area"],
        "periodo": periodo["nombre"], "cerrado": periodo["estado"] == "cerrado",
        "asignado": asignado, "disponible": max(0.0, 100.0 - asignado), "evaluaciones": evals,
    }


def crear_evaluaciones(db, user: dict, datos: dict) -> dict:
    if not isinstance(datos, dict):
        raise invalid("Petición inválida")
    carga_ids = datos.get("carga_ids")
    if (not isinstance(carga_ids, list) or not carga_ids or len(carga_ids) > 12
            or not all(isinstance(c, int) and not isinstance(c, bool) for c in carga_ids)):
        raise invalid("Selecciona al menos una sección", "carga_ids")
    carga_ids = list(dict.fromkeys(carga_ids))

    periodo_id = datos.get("periodo_id")
    if not isinstance(periodo_id, int) or isinstance(periodo_id, bool):
        raise invalid("Selecciona un período", "periodo_id")

    nombre = _texto(datos.get("nombre"), "nombre", 150, obligatorio=True)
    tipo = datos.get("tipo")
    if tipo not in grading.TIPOS_EVALUACION:
        raise invalid("Tipo de instrumento no válido", "tipo")
    competencia = _texto(datos.get("competencia"), "competencia", 200)
    indicadores = _texto(datos.get("indicadores"), "indicadores", 2000)
    fecha = _texto(datos.get("fecha"), "fecha", 10)
    if fecha:
        try:
            date.fromisoformat(fecha)
        except ValueError:
            raise invalid("Fecha no válida (use AAAA-MM-DD)", "fecha")
    maximo = _numero(datos.get("max_puntaje", 100), "max_puntaje", 0, 1000, exclusivo_min=True)
    peso = _numero(datos.get("peso"), "peso", 0, 100, exclusivo_min=True)

    cargas = [carga_propia(db, user["id"], c) for c in carga_ids]
    anio_id = cargas[0]["anio_id"]
    if any(c["anio_id"] != anio_id for c in cargas):
        raise invalid("Las secciones pertenecen a años lectivos distintos", "carga_ids")
    _periodo_abierto(db, periodo_id, anio_id)

    for c in cargas:
        existente = db.scalar(
            "SELECT COALESCE(SUM(peso), 0) FROM evaluaciones WHERE carga_id = ? AND periodo_id = ?",
            (c["id"], periodo_id),
        ) or 0.0
        if existente + peso > 100.0 + 1e-9:
            raise invalid(
                f"En {c['area']} {c['seccion']} ya hay {existente:g}% asignado; "
                f"con {peso:g}% se superaría el 100%",
                "peso",
            )

    ahora = utcnow()
    ids = []
    for c in cargas:
        ids.append(db.insert(
            """
            INSERT INTO evaluaciones (carga_id, periodo_id, nombre, tipo, competencia, fecha,
                                      max_puntaje, peso, indicadores, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (c["id"], periodo_id, nombre, tipo, competencia, fecha, maximo, peso, indicadores,
             user["id"], ahora),
        ))
    db.commit()
    return {"ids": ids, "carga_ids": carga_ids}


def eliminar_evaluacion(db, user: dict, evaluacion_id: int) -> dict:
    fila = db.one(
        """
        SELECT e.id, e.periodo_id, e.carga_id FROM evaluaciones e
        JOIN cargas c ON c.id = e.carga_id
        WHERE e.id = ? AND c.docente_id = ?
        """,
        (evaluacion_id, user["id"]),
    )
    if fila is None:
        raise ApiError(404, "Evaluación no encontrada")
    _periodo_abierto(db, fila["periodo_id"])
    db.execute("DELETE FROM calificaciones WHERE evaluacion_id = ?", (evaluacion_id,))
    db.execute("DELETE FROM evaluaciones WHERE id = ?", (evaluacion_id,))
    db.commit()
    return {"eliminada": evaluacion_id}


# ---------------------------------------------------------------- observaciones
def crear_observacion(db, user: dict, insc_id: int, datos: dict, periodo_id: int | None) -> dict:
    inscripcion_accesible(db, user["id"], insc_id)
    if not isinstance(datos, dict):
        raise invalid("Petición inválida")
    tipo = datos.get("tipo")
    if tipo not in grading.TIPOS_OBSERVACION:
        raise invalid("Tipo de acompañamiento no válido", "tipo")
    descripcion = _texto(datos.get("descripcion"), "descripcion", 2000, obligatorio=True)
    aspecto = _texto(datos.get("aspecto"), "aspecto", 150)

    ahora = utcnow()
    obs_id = db.insert(
        """
        INSERT INTO observaciones (inscripcion_id, periodo_id, tipo, aspecto, descripcion, autor_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (insc_id, periodo_id, tipo, aspecto, descripcion, user["id"], ahora),
    )
    # El tipo de acompañamiento actualiza el estado visible en el panel
    if tipo == "estrategia_recuperacion":
        db.execute("UPDATE inscripciones SET estado_acompanamiento = ? WHERE id = ?", ("Plan de apoyo", insc_id))
    elif tipo == "dificultad":
        db.execute(
            "UPDATE inscripciones SET estado_acompanamiento = ? WHERE id = ? AND estado_acompanamiento IS NULL",
            ("Seguimiento", insc_id),
        )
    db.commit()
    return {
        "id": obs_id, "tipo": tipo, "tipo_label": grading.TIPOS_OBSERVACION[tipo], "aspecto": aspecto,
        "descripcion": descripcion, "autor": user["nombre"], "fecha": fecha_corta(ahora),
    }


# ---------------------------------------------------------------------- cuenta
def cambiar_password(db, user: dict, actual, nueva) -> None:
    if not isinstance(actual, str) or not isinstance(nueva, str):
        raise invalid("Datos inválidos")
    if len(nueva) < MIN_PASSWORD:
        raise invalid(f"La nueva contraseña debe tener al menos {MIN_PASSWORD} caracteres", "nueva")
    if len(nueva) > 200:
        raise invalid("La nueva contraseña es demasiado larga", "nueva")
    fila = db.one("SELECT password_hash FROM usuarios WHERE id = ?", (user["id"],))
    if not fila or not verify_password(fila["password_hash"], actual):
        raise invalid("La contraseña actual no es correcta", "actual")
    db.execute("UPDATE usuarios SET password_hash = ? WHERE id = ?", (hash_password(nueva), user["id"]))
    db.commit()
