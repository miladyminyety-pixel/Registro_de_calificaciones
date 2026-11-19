import pytest

from app import grading as g

# Evaluaciones del diseño (peso == máximo): prácticos 20, pruebas 30, participación 10, proyecto 40
PESOS = [(20, 20), (30, 30), (10, 10), (40, 40)]


def promedio(puntajes):
    items = [(p, m, w) for p, (m, w) in zip(puntajes, PESOS)]
    return g.promedio_ponderado(items)["promedio"]


@pytest.mark.parametrize(
    "puntajes, esperado, literal",
    [
        ([19, 28, 10, 38], 95, "A"),  # María Fernández
        ([14, 19, 7, 28], 68, "D"),  # José Antonio Pérez
        ([18, 25, 9, 36], 88, "B"),  # Ana Martínez
        ([12, 18, 6, 28], 64, "D"),  # Carlos Rodríguez
        ([16, 22, 8, 31], 77, "C"),  # Daniela Ramírez
        ([17, 24, 9, 35], 85, "B"),  # Luis Miguel Santos
    ],
)
def test_matriz_del_diseno(puntajes, esperado, literal):
    assert promedio(puntajes) == esperado
    assert g.literal_de(esperado) == literal


@pytest.mark.parametrize(
    "valor, letra",
    [(100, "A"), (90, "A"), (89.9, "B"), (80, "B"), (79.95, "B"), (79.94, "C"),
     (70, "C"), (69.95, "C"), (69.94, "D"), (0, "D")],
)
def test_limites_de_la_escala(valor, letra):
    # 79.95 se redondea a 80.0 (B) y 69.95 a 70.0 (C): literal y nota mostrada coinciden
    assert g.literal_de(valor) == letra


def test_redondeo_mitad_hacia_arriba():
    assert g.r1(79.25) == 79.3
    assert g.r1(0.05) == 0.1
    assert g.r1(None) is None


def test_literal_y_nota_mostrada_siempre_coinciden():
    # 89.96 se muestra como 90.0: tiene que ser A, no B
    assert g.r1(89.96) == 90.0
    assert g.literal_de(89.96) == "A"


def test_sin_calificar_no_hay_promedio():
    r = g.promedio_ponderado([(None, 20, 20), (None, 30, 30)])
    assert r["promedio"] is None and r["pendientes"] == 2 and r["peso_total"] == 50


def test_se_normaliza_por_el_peso_ya_calificado():
    # Solo la prueba (30 %) está calificada: 24/30 -> 80, no 24 sobre 100
    r = g.promedio_ponderado([(None, 20, 20), (24, 30, 30), (None, 10, 10), (None, 40, 40)])
    assert r["promedio"] == 80.0
    assert r["peso_calificado"] == 30 and r["pendientes"] == 3


def test_distinta_escala_por_evaluacion():
    # Examen sobre 100 con peso 30 y tarea sobre 20 con peso 20
    r = g.promedio_ponderado([(80, 100, 30), (10, 20, 20)])
    assert r["promedio"] == 68.0  # (24 + 10) / 50 * 100


def test_puntaje_fuera_de_rango_se_acota():
    assert g.promedio_ponderado([(150, 100, 100)])["promedio"] == 100.0
    assert g.promedio_ponderado([(-5, 100, 100)])["promedio"] == 0.0


def test_maximo_invalido_se_ignora():
    assert g.promedio_ponderado([(5, 0, 50), (10, 10, 50)])["promedio"] == 100.0


def test_media_ignora_vacios():
    assert g.media([80, None, 90]) == 85.0
    assert g.media([None]) is None


def test_estados():
    assert g.estado_academico("A")["texto"] == "Aprobado con Excelencia"
    assert g.estado_academico("D", "Plan de apoyo")["texto"] == "Plan de Recuperación"
    assert g.estado_academico("D")["texto"] == "Alerta de Acompañamiento"
    assert g.estado_academico(None)["tono"] == "neutral"
    assert g.estado_en_periodo(64, "en_curso") == "En riesgo"
    assert g.estado_en_periodo(64, "cerrado") == "Reprobado"
    assert g.estado_en_periodo(85, "cerrado") == "Aprobado"
    assert g.estado_en_periodo(None, "en_curso") == "Sin datos"
