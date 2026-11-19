import re

import pytest

from app import create_app
from app import security


@pytest.fixture()
def app(tmp_path):
    security.throttle._failures.clear()
    application = create_app({
        "SQLITE_PATH": str(tmp_path / "test.db"),
        "DATABASE_URL": None,
        "SECRET_KEY": "test-secret",
        "ADMIN_USERNAME": "docente",
        "ADMIN_PASSWORD": "clave-segura-123",
        "SEED_DEMO_DATA": True,
        "SESSION_COOKIE_SECURE": False,
        "TESTING": True,
    })
    return application


class Cliente:
    """Cliente de pruebas que maneja el token CSRF automáticamente."""

    def __init__(self, app):
        self.c = app.test_client()
        self.token = None

    def _refrescar_token(self):
        html = self.c.get("/login").get_data(as_text=True)
        m = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.token = m.group(1)

    def login(self, usuario="docente", clave="clave-segura-123"):
        self._refrescar_token()
        r = self.c.post("/login", data={"username": usuario, "password": clave, "csrf_token": self.token})
        if r.status_code == 302:  # la sesión se renueva al entrar: el token se conserva
            pass
        return r

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def api(self, metodo, url, json=None):
        return self.c.open(url, method=metodo, json=json, headers={"X-CSRF-Token": self.token})


@pytest.fixture()
def cliente(app):
    c = Cliente(app)
    assert c.login().status_code == 302
    return c
