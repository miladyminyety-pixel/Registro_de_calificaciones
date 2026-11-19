"""Configuración de la aplicación a partir de variables de entorno."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:  # .env solo para desarrollo local; en Render se usan variables de entorno
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover
    pass


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def is_production() -> bool:
    return bool(os.environ.get("RENDER")) or os.environ.get("APP_ENV") == "production"


def load_config(overrides: dict | None = None) -> dict:
    production = is_production()

    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        if production:
            raise RuntimeError(
                "SECRET_KEY no está definida. En producción es obligatoria "
                "(en Render se genera automáticamente con render.yaml)."
            )
        # Desarrollo: clave efímera; las sesiones se pierden al reiniciar.
        secret_key = secrets.token_hex(32)

    database_url = os.environ.get("DATABASE_URL") or None
    if database_url and database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://"):]

    config = {
        "SECRET_KEY": secret_key,
        "DATABASE_URL": database_url,
        "SQLITE_PATH": os.environ.get("SQLITE_PATH", str(BASE_DIR / "instance" / "registro.db")),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": production,
        "PERMANENT_SESSION_LIFETIME": 60 * 60 * 12,  # 12 horas
        "MAX_CONTENT_LENGTH": 2 * 1024 * 1024,
        "JSON_AS_ASCII": False,
        "PRODUCTION": production,
        # Usuario inicial (solo se crea si no existe ningún usuario)
        "ADMIN_USERNAME": os.environ.get("ADMIN_USERNAME", "").strip(),
        "ADMIN_PASSWORD": os.environ.get("ADMIN_PASSWORD", ""),
        "ADMIN_NAME": (os.environ.get("ADMIN_NAME") or "").strip() or "Docente",
        # Datos de demostración (solo se cargan si la base está vacía)
        "SEED_DEMO_DATA": _flag("SEED_DEMO_DATA", False),
        # Inicialización automática del esquema al arrancar
        "AUTO_INIT_DB": _flag("AUTO_INIT_DB", True),
    }
    if overrides:
        config.update(overrides)
    return config
