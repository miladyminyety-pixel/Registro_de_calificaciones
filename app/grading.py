"""Reglas de calificación (puras, sin base de datos ni Flask).

Escala y criterios tomados del diseño del portal:
    A 90-100 Excelente · B 80-89 Muy Bueno · C 70-79 Bueno · D < 70 Insuficiente
El mínimo aprobatorio es 70.

Cálculo del promedio de un período para un estudiante en un área:
    aporte_i  = puntaje_i / max_i * peso_i
    promedio  = sum(aporte_i) / sum(peso_i de las evaluaciones ya calificadas) * 100

Se normaliza por el peso ya calificado para que, a mitad de período, el promedio
refleje el desempeño real y no un total parcial sobre 100. Cuando todas las
evaluaciones suman 100 % y están calificadas, es exactamente la suma de aportes.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

APROBATORIO = 70.0

# (mínimo, literal, nombre)
ESCALA = [
    (90.0, "A", "Excelente"),
    (80.0, "B", "Muy Bueno"),
    (70.0, "C", "Bueno"),
    (0.0, "D", "Insuficiente"),
]
LITERALES = ["A", "B", "C", "D"]

TIPOS_EVALUACION = {
    "prueba_escrita": {"label": "Prueba Escrita", "icono": "quiz", "peso_sugerido": 30},
    "trabajo_practico": {"label": "Trabajo Práctico", "icono": "science", "peso_sugerido": 20},
    "proyecto_integrador": {"label": "Proyecto Integrador", "icono": "rocket_launch", "peso_sugerido": 25},
    "participacion": {"label": "Participación", "icono": "forum", "peso_sugerido": 10},
}

COMPETENCIAS_FUNDAMENTALES = [
    "Ética y Ciudadana",
    "Comunicativa",
    "Pensamiento Lógico, Creativo y Crítico",
    "Resolución de Problemas",
    "Científica y Tecnológica",
    "Ambiental y de la Salud",
    "Desarrollo Personal y Espiritual",
]

TIPOS_OBSERVACION = {
    "dificultad": "Dificultad Detectada",
    "estrategia_recuperacion": "Estrategia de Recuperación",
    "fortaleza": "Fortaleza Destacada",
    "compromiso_padres": "Compromiso con Padres / Tutores",
}

ESTADOS_ACOMPANAMIENTO = ["En riesgo académico", "Seguimiento", "Plan de apoyo", "Tutoría activa"]


def r1(value: float | None) -> float | None:
    """Redondea a 1 decimal (mitad hacia arriba, como en una calculadora escolar)."""
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def literal_de(promedio: float | None) -> str | None:
    """Literal (A-D) de un promedio ya redondeado a 1 decimal."""
    if promedio is None:
        return None
    valor = r1(promedio)
    for minimo, letra, _nombre in ESCALA:
        if valor >= minimo:
            return letra
    return "D"


def nombre_literal(letra: str | None) -> str:
    for _minimo, l, nombre in ESCALA:
        if l == letra:
            return nombre
    return ""


def aprobado(promedio: float | None) -> bool:
    return promedio is not None and r1(promedio) >= APROBATORIO


def promedio_ponderado(items: Iterable[tuple[float | None, float, float]]) -> dict:
    """Promedio de un período a partir de (puntaje|None, max_puntaje, peso).

    Devuelve promedio (None si no hay nada calificado), peso calificado, peso
    total planificado y cantidad de evaluaciones pendientes de calificar.
    """
    aporte = 0.0
    peso_calificado = 0.0
    peso_total = 0.0
    pendientes = 0
    total = 0
    for puntaje, maximo, peso in items:
        if not maximo or maximo <= 0:
            continue
        total += 1
        peso_total += peso
        if puntaje is None:
            pendientes += 1
            continue
        valor = min(max(float(puntaje), 0.0), float(maximo))
        aporte += valor / maximo * peso
        peso_calificado += peso
    promedio = r1(aporte / peso_calificado * 100.0) if peso_calificado > 0 else None
    return {
        "promedio": promedio,
        "peso_calificado": peso_calificado,
        "peso_total": peso_total,
        "pendientes": pendientes,
        "evaluaciones": total,
    }


def media(valores: Iterable[float | None]) -> float | None:
    lista = [v for v in valores if v is not None]
    if not lista:
        return None
    return r1(sum(lista) / len(lista))


def estado_academico(literal: str | None, acompanamiento: str | None = None) -> dict:
    """Etiqueta e icono del 'Estado académico' en la matriz de calificaciones."""
    if literal is None:
        return {"texto": "Sin calificar", "icono": "pending", "tono": "neutral"}
    if literal == "A":
        return {"texto": "Aprobado con Excelencia", "icono": "stars", "tono": "A"}
    if literal == "B":
        return {"texto": "Aprobado Satisfactorio", "icono": "check_circle", "tono": "B"}
    if literal == "C":
        return {"texto": "Aprobado Básico", "icono": "verified_user", "tono": "C"}
    if acompanamiento in ("Plan de apoyo", "Tutoría activa"):
        return {"texto": "Plan de Recuperación", "icono": "crisis_alert", "tono": "D"}
    return {"texto": "Alerta de Acompañamiento", "icono": "warning", "tono": "D"}


def estado_en_periodo(promedio: float | None, estado_periodo: str) -> str:
    """Estado mostrado en el histórico del perfil del estudiante."""
    if promedio is None:
        return "Sin datos"
    if not aprobado(promedio):
        return "En riesgo" if estado_periodo != "cerrado" else "Reprobado"
    return "En curso" if estado_periodo != "cerrado" else "Aprobado"
