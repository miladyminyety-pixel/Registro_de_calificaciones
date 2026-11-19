"""Autenticación por sesión, protección CSRF y límite de intentos de acceso."""
from __future__ import annotations

import hmac
import secrets
import threading
import time
from functools import wraps

from flask import abort, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

MIN_PASSWORD = 8
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


# --------------------------------------------------------------------- usuarios
def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    return check_password_hash(stored_hash, password)


def current_user() -> dict | None:
    if "user" in g:
        return g.user
    user = None
    uid = session.get("uid")
    if uid:
        user = get_db().one(
            "SELECT id, username, nombre, cargo, nivel FROM usuarios WHERE id = ? AND activo = 1",
            (uid,),
        )
        if user is None:
            session.clear()
    g.user = user
    return user


def login_user(user_id: int) -> None:
    csrf = session.get("csrf")
    session.clear()  # evita fijación de sesión
    session["uid"] = user_id
    session["csrf"] = csrf or secrets.token_urlsafe(32)
    session.permanent = True


def logout_user() -> None:
    session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Sesión no iniciada"}), 401
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def safe_next(target: str | None) -> str:
    """Solo se permiten redirecciones internas (evita open redirect)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("pages.dashboard")


# ------------------------------------------------------------------------- CSRF
def csrf_token() -> str:
    token = session.get("csrf")
    if not token:
        token = session["csrf"] = secrets.token_urlsafe(32)
    return token


def verify_csrf() -> None:
    """Exige el token en toda petición que modifica datos."""
    if request.method in _SAFE_METHODS:
        return
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    expected = session.get("csrf") or ""
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, description="Token CSRF inválido. Recarga la página e inténtalo de nuevo.")


# ------------------------------------------------------------ límite de intentos
class LoginThrottle:
    """Bloqueo temporal tras demasiados intentos fallidos (por IP + usuario).

    Vive en memoria de cada proceso: frena la fuerza bruta básica, no sustituye a
    un firewall/WAF.
    """

    def __init__(self, max_failures: int = 5, window: int = 15 * 60):
        self.max_failures = max_failures
        self.window = window
        self._failures: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key, now):
        recent = [t for t in self._failures.get(key, []) if now - t < self.window]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def retry_after(self, ip: str, username: str) -> int:
        """Segundos hasta poder reintentar (0 si no está bloqueado)."""
        key = (ip, username.lower())
        now = time.time()
        with self._lock:
            recent = self._recent(key, now)
            if len(recent) >= self.max_failures:
                return max(1, int(self.window - (now - recent[0])))
        return 0

    def fail(self, ip: str, username: str) -> None:
        key = (ip, username.lower())
        now = time.time()
        with self._lock:
            self._recent(key, now)
            self._failures.setdefault(key, []).append(now)
            if len(self._failures) > 5000:  # acota la memoria
                oldest = sorted(self._failures, key=lambda k: self._failures[k][-1])[:1000]
                for k in oldest:
                    self._failures.pop(k, None)

    def reset(self, ip: str, username: str) -> None:
        with self._lock:
            self._failures.pop((ip, username.lower()), None)


throttle = LoginThrottle()
