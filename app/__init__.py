"""Registro de Calificaciones — aplicación Flask."""
from __future__ import annotations

import logging

from flask import Flask, jsonify, render_template, request, session

from . import db as database
from .config import load_config
from .data import fecha_corta, resolver_contexto
from .errors import ApiError
from .security import csrf_token, current_user, verify_csrf


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(load_config(overrides))
    app.json.ensure_ascii = False
    logging.basicConfig(level=logging.INFO)

    if app.config["PRODUCTION"]:
        # Render termina TLS en un único proxy: se confía solo en un salto de X-Forwarded-*
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.teardown_appcontext(database.close_db)

    # --- seguridad -------------------------------------------------------------
    app.before_request(verify_csrf)

    @app.after_request
    def cabeceras(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if app.config["PRODUCTION"]:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if request.path.startswith("/api/") or request.endpoint in ("auth.login",):
            resp.headers["Cache-Control"] = "no-store"
        elif current_user_cached():
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    def current_user_cached():
        from flask import g
        return g.get("user")

    # --- plantillas ------------------------------------------------------------
    @app.context_processor
    def globales():
        user = current_user()
        ctx = None
        if user:
            ctx = resolver_contexto(database.get_db(), session.get("anio_id"), session.get("periodo_id"))
        return {"usuario": user, "ctx": ctx, "csrf_token": csrf_token}

    app.jinja_env.filters["fecha"] = fecha_corta
    app.jinja_env.filters["nota"] = lambda v: "—" if v is None else (f"{v:.1f}".rstrip("0").rstrip("."))
    app.jinja_env.filters["pct"] = lambda v: "—" if v is None else f"{v:g}"

    # --- errores ---------------------------------------------------------------
    @app.errorhandler(ApiError)
    def api_error(exc: ApiError):
        if request.path.startswith("/api/"):
            return jsonify(exc.to_dict()), exc.status
        return render_template("error.html", codigo=exc.status, mensaje=exc.message), exc.status

    def _http(codigo, mensaje):
        def handler(exc):
            propia = getattr(exc, "description", None)
            # el texto por defecto de Werkzeug está en inglés: solo se usa si es uno nuestro
            descripcion = propia if propia and propia != type(exc).description else mensaje
            if request.path.startswith("/api/"):
                return jsonify({"error": descripcion}), codigo
            return render_template("error.html", codigo=codigo, mensaje=descripcion), codigo
        return handler

    app.register_error_handler(400, _http(400, "Petición no válida"))
    app.register_error_handler(404, _http(404, "No encontramos lo que buscas"))
    app.register_error_handler(405, _http(405, "Método no permitido"))
    app.register_error_handler(413, _http(413, "La petición es demasiado grande"))

    @app.errorhandler(500)
    def interno(exc):
        app.logger.exception("Error interno")
        mensaje = "Ocurrió un error inesperado. Inténtalo de nuevo en unos minutos."
        if request.path.startswith("/api/"):
            return jsonify({"error": mensaje}), 500
        return render_template("error.html", codigo=500, mensaje=mensaje), 500

    # --- rutas -----------------------------------------------------------------
    from .routes import api, auth, pages

    app.register_blueprint(auth.bp)
    app.register_blueprint(pages.bp)
    app.register_blueprint(api.bp)

    @app.get("/healthz")
    def healthz():
        database.get_db().scalar("SELECT 1")
        return jsonify({"estado": "ok"})

    # --- inicialización de la base de datos -----------------------------------
    if app.config["AUTO_INIT_DB"]:
        with app.app_context():
            inicializar(app)

    return app


def inicializar(app: Flask) -> None:
    """Esquema + catálogo + usuario inicial + (opcional) datos de demostración."""
    from . import seed

    conn = database.connect(app.config)
    try:
        with database.startup_lock(conn):
            database.init_schema(conn)
            seed.seed_base(conn)
            cfg = app.config
            if seed.crear_admin(conn, cfg["ADMIN_USERNAME"], cfg["ADMIN_PASSWORD"], cfg["ADMIN_NAME"]):
                app.logger.info("Usuario inicial '%s' creado", cfg["ADMIN_USERNAME"])
            elif not conn.scalar("SELECT COUNT(*) FROM usuarios"):
                app.logger.warning(
                    "No hay usuarios y no se pudo crear el inicial: define ADMIN_USERNAME y "
                    "ADMIN_PASSWORD (mínimo 8 caracteres) para poder iniciar sesión.")
            if cfg["SEED_DEMO_DATA"]:
                docente = conn.one("SELECT id FROM usuarios ORDER BY id LIMIT 1")
                if docente and seed.seed_demo(conn, docente["id"]):
                    app.logger.info("Datos de demostración cargados")
    finally:
        conn.close()
