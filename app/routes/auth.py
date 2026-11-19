from flask import Blueprint, redirect, render_template, request, session, url_for

from ..db import get_db
from ..security import (
    login_user, logout_user, safe_next, throttle, verify_password,
)

bp = Blueprint("auth", __name__)

# Hash ficticio: se compara igualmente cuando el usuario no existe, para que el
# tiempo de respuesta no revele si el usuario está registrado.
_DUMMY_HASH = "scrypt:32768:8:1$x$" + "0" * 128


@bp.route("/login", methods=["GET", "POST"])
def login():
    siguiente = request.args.get("next") or request.form.get("next") or ""
    if request.method == "GET":
        return render_template("login.html", error=None, next=siguiente, username="")

    username = (request.form.get("username") or "").strip().lower()[:80]
    password = request.form.get("password") or ""
    # remote_addr es fiable: en producción ProxyFix toma la IP que añade el proxy de Render
    # (no el valor que envíe el cliente en X-Forwarded-For, que se puede falsificar).
    ip = request.remote_addr or "?"

    espera = throttle.retry_after(ip, username)
    if espera:
        minutos = max(1, round(espera / 60))
        return render_template(
            "login.html", next=siguiente, username=username,
            error=f"Demasiados intentos fallidos. Inténtalo de nuevo en {minutos} min."), 429

    user = get_db().one(
        "SELECT id, password_hash FROM usuarios WHERE username = ? AND activo = 1", (username,))
    try:
        correcto = verify_password(user["password_hash"] if user else _DUMMY_HASH, password) and bool(user)
    except ValueError:
        correcto = False
    if not correcto:
        throttle.fail(ip, username)
        return render_template("login.html", next=siguiente, username=username,
                               error="Usuario o contraseña incorrectos."), 401

    throttle.reset(ip, username)
    login_user(user["id"])
    return redirect(safe_next(siguiente))


@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
