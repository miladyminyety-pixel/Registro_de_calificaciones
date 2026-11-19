"""Capa de acceso a datos.

Un mismo SQL (con marcadores ``?``) funciona en SQLite (desarrollo/pruebas) y en
PostgreSQL (producción, p. ej. Render). Las diferencias de dialecto se concentran
aquí y en ``schema.py``.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g

from .schema import SCHEMA

# Identificador del bloqueo asesor de PostgreSQL usado al inicializar el esquema,
# para que varios procesos arrancando a la vez no choquen.
_PG_LOCK_ID = 7_274_001


def utcnow() -> str:
    """Fecha/hora UTC en ISO 8601 (se guarda como texto: portable entre motores)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Conn:
    """Conexión con una API mínima e idéntica para ambos motores."""

    def __init__(self, raw, dialect: str):
        self.raw = raw
        self.dialect = dialect

    @property
    def is_postgres(self) -> bool:
        return self.dialect == "postgres"

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.is_postgres else sql

    def query(self, sql: str, params: tuple | list = ()) -> list[dict]:
        cur = self.raw.cursor()
        try:
            cur.execute(self._sql(sql), tuple(params))
            return [dict(row) for row in cur.fetchall()]
        finally:
            cur.close()

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: tuple | list = ()):
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        cur = self.raw.cursor()
        try:
            cur.execute(self._sql(sql), tuple(params))
            return cur.rowcount
        finally:
            cur.close()

    def executemany(self, sql: str, seq) -> None:
        cur = self.raw.cursor()
        try:
            cur.executemany(self._sql(sql), [tuple(p) for p in seq])
        finally:
            cur.close()

    def insert(self, sql: str, params: tuple | list = ()) -> int:
        """INSERT que devuelve el id generado (RETURNING funciona en ambos motores)."""
        row = self.one(sql.rstrip().rstrip(";") + " RETURNING id", params)
        return int(row["id"])

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        try:
            self.raw.close()
        except Exception:  # pragma: no cover
            pass


def connect(config: dict) -> Conn:
    url = config.get("DATABASE_URL")
    if url:
        import psycopg  # se importa aquí: solo hace falta en producción
        from psycopg.rows import dict_row

        raw = psycopg.connect(url, row_factory=dict_row, connect_timeout=15)
        return Conn(raw, "postgres")

    path = Path(config["SQLITE_PATH"])
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(str(path), timeout=15)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    return Conn(raw, "sqlite")


def get_db() -> Conn:
    """Conexión de la petición actual (se cierra sola al terminar)."""
    if "db" not in g:
        g.db = connect(current_app.config)
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        if _exc is not None:
            conn.rollback()
        conn.close()


@contextmanager
def startup_lock(conn: Conn):
    """Exclusión mutua del arranque (esquema + datos iniciales) entre procesos.

    En PostgreSQL usa un bloqueo asesor de sesión; en SQLite no hace falta.
    """
    if conn.is_postgres:
        conn.query("SELECT pg_advisory_lock(?)", (_PG_LOCK_ID,))
        conn.commit()
    try:
        yield
    finally:
        if conn.is_postgres:
            conn.rollback()
            conn.query("SELECT pg_advisory_unlock(?)", (_PG_LOCK_ID,))
            conn.commit()


def init_schema(conn: Conn) -> None:
    """Crea las tablas si no existen (idempotente)."""
    pk = "SERIAL PRIMARY KEY" if conn.is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    try:
        for statement in SCHEMA:
            conn.execute(statement.replace("{PK}", pk))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
