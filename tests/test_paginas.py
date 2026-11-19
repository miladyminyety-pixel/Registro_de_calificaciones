import pytest

PAGINAS = ["/dashboard", "/dashboard?seccion=1", "/mis-secciones", "/areas", "/areas?seccion=1",
           "/registro", "/estudiantes", "/estudiantes?q=maria&alerta=1", "/evaluaciones",
           "/evaluaciones/nueva", "/configuracion", "/reportes", "/acerca"]


@pytest.mark.parametrize("url", PAGINAS)
def test_pagina_renderiza(cliente, url):
    r = cliente.get(url)
    assert r.status_code == 200, r.get_data(as_text=True)[:500]


def test_perfil_renderiza(cliente):
    r = cliente.get("/estudiantes/1")
    assert r.status_code == 200
    assert "Histórico académico" in r.get_data(as_text=True)
