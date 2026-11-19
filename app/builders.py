"""Modelos de datos de cada pantalla (lo que consumen las plantillas y la API)."""
from __future__ import annotations

import math
import unicodedata
from collections import defaultdict

from . import grading
from .data import (
    Datos,
    cargas_docente,
    cargas_visibles_en_seccion,
    carga_propia,
    fecha_corta,
    inscripcion_accesible,
)
from .errors import not_found

DONUT_R = 38
DONUT_C = 2 * math.pi * DONUT_R  # circunferencia del donut del dashboard
# Colores de la leyenda del dashboard (A, B, C, D)
DONUT_COLORES = {"A": "#ae2b4b", "B": "#3178b9", "C": "#0861a1", "D": "#ba1a1a"}


def _normalizar(texto: str) -> str:
    base = unicodedata.normalize("NFD", texto or "")
    return "".join(ch for ch in base if unicodedata.category(ch) != "Mn").lower().strip()


def _periodo_ids(ctx: dict) -> list[int]:
    return [p["id"] for p in ctx["periodos"]]


def _secciones_de(cargas: list[dict]) -> list[dict]:
    vistas, salida = set(), []
    for c in cargas:
        if c["seccion_id"] not in vistas:
            vistas.add(c["seccion_id"])
            salida.append({"id": c["seccion_id"], "seccion": c["seccion"]})
    return sorted(salida, key=lambda s: s["seccion"])


# -------------------------------------------------------------------- dashboard
def dashboard(db, user: dict, ctx: dict, seccion_id: int | None = None) -> dict:
    anio, periodo = ctx["anio"], ctx["periodo"]
    if not anio or not periodo:
        return {"vacio": True, "secciones": [], "seccion_id": None}

    todas = cargas_docente(db, user["id"], anio["id"])
    secciones = _secciones_de(todas)
    if seccion_id not in {s["id"] for s in secciones}:
        seccion_id = None
    cargas = [c for c in todas if not seccion_id or c["seccion_id"] == seccion_id]
    if not cargas:
        return {"vacio": True, "secciones": secciones, "seccion_id": seccion_id}

    datos = Datos(db, cargas, _periodo_ids(ctx))
    pid = periodo["id"]

    por_insc: dict[int, list[tuple[float, dict]]] = defaultdict(list)
    por_area: dict[int, list[float]] = defaultdict(list)
    insc_info: dict[int, dict] = {}
    for c in cargas:
        for i in datos.estudiantes_de(c["id"]):
            insc_info[i["id"]] = i
            p = datos.resultado(c["id"], pid, i["id"])["promedio"]
            if p is not None:
                por_insc[i["id"]].append((p, c))
                por_area[c["area_id"]].append(p)

    # Estudiantes por sección
    por_seccion = {}
    for c in cargas:
        por_seccion[c["seccion"]] = len(datos.estudiantes_de(c["id"]))
    por_seccion = dict(sorted(por_seccion.items()))

    # Áreas
    areas_ordenadas: dict[int, dict] = {}
    for c in cargas:
        areas_ordenadas.setdefault(c["area_id"], c)
    barras = []
    for area_id, c in areas_ordenadas.items():
        m = grading.media(por_area.get(area_id, []))
        barras.append({"area": c["area_titulo"], "promedio": m, "literal": grading.literal_de(m)})
    barras.sort(key=lambda b: (b["promedio"] is None, -(b["promedio"] or 0)))

    todos = [p for lista in por_area.values() for p in lista]
    prom_general = grading.media(todos)

    # Planificación: cargas cuyas ponderaciones del período suman 100 %
    completas = sum(
        1 for c in cargas
        if abs(sum(e["peso"] for e in datos.evaluaciones_de(c["id"], pid)) - 100.0) < 1e-6
    )
    planificacion = round(100 * completas / len(cargas))

    # Atención prioritaria: estudiantes con alguna área < 70
    alertas = []
    for insc_id, lista in por_insc.items():
        peor, carga = min(lista, key=lambda t: t[0])
        if not grading.aprobado(peor):
            i = insc_info[insc_id]
            alertas.append({
                "insc_id": insc_id, "nombre": i["nombre"], "iniciales": i["iniciales"],
                "matricula": i["matricula"], "seccion": carga["seccion"],
                "nivel": f"{carga['grado_nombre']} · {i['condicion']}",
                "area": carga["area"], "area_icono": carga["icono"],
                "promedio": peor, "literal": grading.literal_de(peor),
                "acompanamiento": i["estado_acompanamiento"],
            })
    alertas.sort(key=lambda a: (a["promedio"], a["nombre"]))

    # Distribución de literales por promedio general del estudiante
    dist = {l: 0 for l in grading.LITERALES}
    for lista in por_insc.values():
        dist[grading.literal_de(grading.media([p for p, _ in lista]))] += 1
    evaluados = sum(dist.values())
    segmentos, acumulado = [], 0.0
    for letra in grading.LITERALES:
        largo = (dist[letra] / evaluados * DONUT_C) if evaluados else 0.0
        segmentos.append({
            "literal": letra, "color": DONUT_COLORES[letra],
            "dasharray": f"{largo:.2f} {DONUT_C - largo:.2f}", "dashoffset": f"{-acumulado:.2f}",
        })
        acumulado += largo
    distribucion = [
        {"literal": l, "cantidad": dist[l], "pct": round(100 * dist[l] / evaluados) if evaluados else 0}
        for l in grading.LITERALES
    ]

    # Evolución por período
    evolucion = []
    for p in ctx["periodos"]:
        valores = [
            v for c in cargas for v in datos.promedios(c["id"], p["id"]).values()
        ]
        media = grading.media(valores)
        if media is not None:
            etiqueta = "Consolidado final" if p["estado"] == "cerrado" else "Promedio actual"
            valor, sub = media, f"Literal {grading.literal_de(media)}"
        elif p["meta"]:
            valor, etiqueta, sub = p["meta"], "Meta estimada", "Objetivo"
        else:
            valor, etiqueta, sub = None, "En programación", ""
        evolucion.append({
            "numero": p["numero"], "nombre": p["nombre"], "valor": valor,
            "etiqueta": etiqueta, "sub": sub, "real": media is not None, "actual": p["id"] == pid,
        })

    return {
        "vacio": False,
        "secciones": secciones,
        "seccion_id": seccion_id,
        "n_areas": len(areas_ordenadas),
        "n_estudiantes": len(insc_info),
        "por_seccion": por_seccion,
        "planificacion_pct": planificacion,
        "promedio_general": prom_general,
        "literal_general": grading.literal_de(prom_general),
        "calificaciones": len(todos),
        "n_alertas": len(alertas),
        "alertas": alertas,
        "barras": barras,
        "evaluados": evaluados,
        "distribucion": distribucion,
        "segmentos": segmentos,
        "evolucion": evolucion,
    }


# ------------------------------------------------------------------------ áreas
def areas_resumen(db, user: dict, ctx: dict, seccion_id: int | None = None) -> dict:
    anio, periodo = ctx["anio"], ctx["periodo"]
    if not anio or not periodo:
        return {"vacio": True, "areas": [], "secciones": [], "seccion_id": None}
    todas = cargas_docente(db, user["id"], anio["id"])
    secciones = _secciones_de(todas)
    if seccion_id not in {s["id"] for s in secciones}:
        seccion_id = None
    cargas = [c for c in todas if not seccion_id or c["seccion_id"] == seccion_id]
    datos = Datos(db, cargas, [periodo["id"]])
    pid = periodo["id"]

    grupos: dict[int, list[dict]] = defaultdict(list)
    for c in cargas:
        grupos[c["area_id"]].append(c)

    areas = []
    for area_id, lista in grupos.items():
        primera = lista[0]
        proms = [p for c in lista for p in datos.promedios(c["id"], pid).values()]
        prom = grading.media(proms)
        hechas = esperadas = pendientes = 0
        for c in lista:
            h, e = datos.celdas(c["id"], pid)
            hechas, esperadas = hechas + h, esperadas + e
            estudiantes = datos.estudiantes_de(c["id"])
            for ev in datos.evaluaciones_de(c["id"], pid):
                if any(datos.puntajes.get((ev["id"], i["id"])) is None for i in estudiantes):
                    pendientes += 1
        areas.append({
            "area_id": area_id,
            "nombre": primera["area"],
            "categoria": primera["categoria"],
            "icono": primera["icono"],
            "estilo": primera["estilo"],
            "secciones": [{"id": c["seccion_id"], "seccion": c["seccion"], "carga_id": c["id"]} for c in lista],
            "estudiantes": sum(len(datos.estudiantes_de(c["id"])) for c in lista),
            "promedio": prom,
            "literal": grading.literal_de(prom),
            "evaluaciones": max((len(datos.evaluaciones_de(c["id"], pid)) for c in lista), default=0),
            "completado": round(100 * hechas / esperadas) if esperadas else None,
            "pendientes": pendientes,
        })
    return {
        "vacio": not areas,
        "areas": areas,
        "secciones": secciones,
        "seccion_id": seccion_id,
        "n_areas": len(areas),
        "n_cargas": len(cargas),
        "n_con_pendientes": sum(1 for a in areas if a["pendientes"]),
    }


# ----------------------------------------------------------------------- matriz
def matriz(db, user: dict, carga_id: int, periodo_id: int) -> dict:
    carga = carga_propia(db, user["id"], carga_id)
    periodo = db.one(
        "SELECT id, anio_id, numero, nombre, estado FROM periodos WHERE id = ?", (periodo_id,)
    )
    if periodo is None or periodo["anio_id"] != carga["anio_id"]:
        raise not_found("Período no encontrado")
    datos = Datos(db, [carga], [periodo_id])
    evals = datos.evaluaciones_de(carga_id, periodo_id)

    filas = []
    for n, insc in enumerate(datos.estudiantes_de(carga_id), 1):
        r = datos.resultado(carga_id, periodo_id, insc["id"])
        literal = grading.literal_de(r["promedio"])
        filas.append({
            "n": n,
            "insc_id": insc["id"],
            "matricula": insc["matricula"],
            "rne": insc["rne"],
            "nombre": insc["nombre"],
            "iniciales": insc["iniciales"],
            "valores": {e["id"]: datos.puntajes.get((e["id"], insc["id"])) for e in evals},
            "promedio": r["promedio"],
            "literal": literal,
            "pendientes": r["pendientes"],
            "estado": grading.estado_academico(literal, insc["estado_acompanamiento"]),
        })

    proms = [f["promedio"] for f in filas if f["promedio"] is not None]
    aprobados = sum(1 for p in proms if grading.aprobado(p))
    hechas, esperadas = datos.celdas(carga_id, periodo_id)
    peso_total = sum(e["peso"] for e in evals)
    return {
        "carga": carga,
        "periodo": periodo,
        "evaluaciones": evals,
        "filas": filas,
        "peso_total": peso_total,
        "planificacion_completa": abs(peso_total - 100.0) < 1e-6,
        "resumen": {
            "total": len(filas),
            "promedio": grading.media(proms),
            "tasa_aprobacion": grading.r1(100.0 * aprobados / len(proms)) if proms else None,
            "pendientes": esperadas - hechas,
        },
    }


# ----------------------------------------------------------------------- perfil
def _diagnostico(filas: list[dict]) -> dict:
    con_datos = [f for f in filas if f["promedio"] is not None]
    if not con_datos:
        return {"titulo": "Sin calificaciones registradas",
                "texto": "Todavía no hay evaluaciones calificadas para este estudiante.",
                "accion": None}
    criticas = [f for f in con_datos if not grading.aprobado(f["promedio"])]
    resto = [f for f in con_datos if grading.aprobado(f["promedio"])]
    if not criticas:
        return {"titulo": "Estado: Rendimiento satisfactorio en todas las áreas evaluadas",
                "texto": f"Todas las áreas evaluadas están en {int(grading.APROBATORIO)} puntos o más.",
                "accion": None}
    nombres = ", ".join(f["area"] for f in criticas)
    detalle = ", ".join(f"{f['area']} ({grading.r1(f['promedio']):g})" for f in criticas)
    texto = f"Promedio inferior a {int(grading.APROBATORIO)} puntos en: {detalle}."
    if resto:
        bajo = min(f["promedio"] for f in resto)
        alto = max(f["promedio"] for f in resto)
        texto += f" En las demás áreas evaluadas los promedios van de {bajo:g} a {alto:g} puntos."
    texto += " Se recomienda definir un plan de nivelación y dejar constancia en la bitácora de acompañamiento."
    resumen = "demás asignaturas sin alerta" if resto else "sin otras áreas evaluadas"
    return {"titulo": f"Estado: Alerta de desempeño en {nombres} — {resumen}",
            "texto": texto, "accion": nombres}


def perfil(db, user: dict, insc_id: int, ctx: dict) -> dict:
    insc = inscripcion_accesible(db, user["id"], insc_id)
    periodos = db.query(
        "SELECT id, numero, nombre, estado FROM periodos WHERE anio_id = ? ORDER BY numero",
        (insc["anio_id"],),
    )
    anio = db.one("SELECT id, nombre FROM anios_lectivos WHERE id = ?", (insc["anio_id"],))
    actual = ctx["periodo"] if ctx["periodo"] and ctx["periodo"]["id"] in {p["id"] for p in periodos} else None
    if actual is None:
        actual = next((p for p in periodos if p["estado"] == "en_curso"), periodos[0] if periodos else None)

    cargas = cargas_visibles_en_seccion(db, user["id"], insc["seccion_id"], insc["tutor_id"])
    datos = Datos(db, cargas, [p["id"] for p in periodos])

    filas = []
    for c in cargas:
        por_periodo = {p["id"]: datos.resultado(c["id"], p["id"], insc_id)["promedio"] for p in periodos}
        valores = [v for v in por_periodo.values() if v is not None]
        prom = grading.media(valores)
        ultimo = next((p for p in reversed(periodos) if por_periodo[p["id"]] is not None), None)
        desglose = []
        if actual:
            for e in datos.evaluaciones_de(c["id"], actual["id"]):
                puntaje = datos.puntajes.get((e["id"], insc_id))
                pct = grading.r1(puntaje / e["max_puntaje"] * 100.0) if puntaje is not None else None
                desglose.append({"nombre": e["nombre"], "pct": pct})
        filas.append({
            "carga_id": c["id"], "area": c["area_titulo"], "area_corta": c["area"], "icono": c["icono"],
            "periodos": por_periodo, "promedio": prom, "literal": grading.literal_de(prom),
            "estado": grading.estado_en_periodo(prom, ultimo["estado"] if ultimo else "en_curso"),
            "desglose": desglose,
        })

    proms = [f["promedio"] for f in filas if f["promedio"] is not None]
    general = grading.media(proms)
    aprobadas = sum(1 for p in proms if grading.aprobado(p))
    criticas = [f for f in filas if f["promedio"] is not None and not grading.aprobado(f["promedio"])]

    if criticas:
        if insc["estado_acompanamiento"]:
            estado_general = {"titulo": "En Seguimiento", "detalle": insc["estado_acompanamiento"], "alerta": True}
        else:
            estado_general = {"titulo": "Requiere Atención", "detalle": "Sin plan de apoyo registrado", "alerta": True}
    elif proms:
        estado_general = {"titulo": "Sin Alertas", "detalle": "Rendimiento satisfactorio", "alerta": False}
    else:
        estado_general = {"titulo": "Sin Datos", "detalle": "Aún sin calificaciones", "alerta": False}

    centro = db.one(
        "SELECT nombre, regional, distrito FROM centros WHERE id = ?", (insc["centro_id"],)
    ) or {}
    tutor = db.one("SELECT nombre FROM usuarios WHERE id = ?", (insc["tutor_id"],)) if insc["tutor_id"] else None

    observaciones = db.query(
        """
        SELECT o.id, o.tipo, o.aspecto, o.descripcion, o.created_at, u.nombre AS autor
        FROM observaciones o JOIN usuarios u ON u.id = o.autor_id
        WHERE o.inscripcion_id = ?
        ORDER BY o.created_at DESC, o.id DESC
        """,
        (insc_id,),
    )
    for o in observaciones:
        o["fecha"] = fecha_corta(o["created_at"])
        o["tipo_label"] = grading.TIPOS_OBSERVACION.get(o["tipo"], o["tipo"])

    return {
        "insc": insc,
        "anio": anio,
        "periodos": periodos,
        "periodo": actual,
        "centro": centro,
        "tutor": tutor["nombre"] if tutor else None,
        "filas": filas,
        "kpi": {
            "promedio": general, "literal": grading.literal_de(general),
            "literal_nombre": grading.nombre_literal(grading.literal_de(general)),
            "areas": len(filas), "evaluadas": len(proms), "aprobadas": aprobadas,
            "aprobadas_pct": grading.r1(100.0 * aprobadas / len(proms)) if proms else None,
            "criticas": [{"area": f["area_corta"], "promedio": f["promedio"]} for f in criticas],
        },
        "estado_general": estado_general,
        "diagnostico": _diagnostico(filas),
        "observaciones": observaciones,
    }


# ------------------------------------------------------------------ estudiantes
def estudiantes(db, user: dict, ctx: dict, q: str = "", seccion_id: int | None = None,
                solo_alerta: bool = False) -> dict:
    anio, periodo = ctx["anio"], ctx["periodo"]
    if not anio or not periodo:
        return {"vacio": True, "filas": [], "secciones": [], "seccion_id": None}
    todas = cargas_docente(db, user["id"], anio["id"])
    secciones = _secciones_de(todas)
    if seccion_id not in {s["id"] for s in secciones}:
        seccion_id = None
    cargas = [c for c in todas if not seccion_id or c["seccion_id"] == seccion_id]
    datos = Datos(db, cargas, [periodo["id"]])

    acumulado: dict[int, dict] = {}
    for c in cargas:
        for i in datos.estudiantes_de(c["id"]):
            fila = acumulado.setdefault(i["id"], {"insc": i, "seccion": c["seccion"], "proms": [], "peor": None})
            p = datos.resultado(c["id"], periodo["id"], i["id"])["promedio"]
            if p is not None:
                fila["proms"].append(p)
                if fila["peor"] is None or p < fila["peor"][0]:
                    fila["peor"] = (p, c["area"])

    consulta = _normalizar(q)
    filas = []
    for fila in acumulado.values():
        i = fila["insc"]
        if consulta and consulta not in _normalizar(f"{i['nombre']} {i['matricula']} {i['rne'] or ''}"):
            continue
        general = grading.media(fila["proms"])
        en_alerta = fila["peor"] is not None and not grading.aprobado(fila["peor"][0])
        if solo_alerta and not en_alerta:
            continue
        filas.append({
            "insc_id": i["id"], "nombre": i["nombre"], "iniciales": i["iniciales"],
            "apellidos": i["apellidos"], "matricula": i["matricula"], "rne": i["rne"],
            "seccion": fila["seccion"], "condicion": i["condicion"],
            "promedio": general, "literal": grading.literal_de(general),
            "alerta": en_alerta, "area_critica": fila["peor"][1] if en_alerta else None,
            "acompanamiento": i["estado_acompanamiento"],
        })
    filas.sort(key=lambda f: (f["apellidos"].lower(), f["nombre"].lower()))
    return {"vacio": False, "filas": filas, "secciones": secciones, "seccion_id": seccion_id,
            "q": q, "solo_alerta": solo_alerta}


# ---------------------------------------------------------------- evaluaciones
def evaluaciones_lista(db, user: dict, ctx: dict) -> dict:
    anio, periodo = ctx["anio"], ctx["periodo"]
    if not anio or not periodo:
        return {"vacio": True, "cargas": []}
    cargas = cargas_docente(db, user["id"], anio["id"])
    datos = Datos(db, cargas, [periodo["id"]])
    salida = []
    for c in cargas:
        estudiantes_c = datos.estudiantes_de(c["id"])
        evals = []
        for e in datos.evaluaciones_de(c["id"], periodo["id"]):
            hechas = sum(1 for i in estudiantes_c if datos.puntajes.get((e["id"], i["id"])) is not None)
            evals.append({
                "id": e["id"], "nombre": e["nombre"],
                "tipo": grading.TIPOS_EVALUACION.get(e["tipo"], {}).get("label", e["tipo"]),
                "icono": grading.TIPOS_EVALUACION.get(e["tipo"], {}).get("icono", "assignment"),
                "fecha": fecha_corta(e["fecha"]), "peso": e["peso"], "max": e["max_puntaje"],
                "calificadas": hechas, "total": len(estudiantes_c),
            })
        peso = sum(e["peso"] for e in evals)
        salida.append({"carga": c, "evaluaciones": evals, "peso_total": peso,
                       "completa": abs(peso - 100.0) < 1e-6})
    return {"vacio": not salida, "cargas": salida}
