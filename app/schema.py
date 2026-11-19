"""Esquema de la base de datos (SQL portable SQLite/PostgreSQL).

Convenciones para que el mismo SQL sirva en ambos motores:
- ``{PK}`` se sustituye por la clave primaria autoincremental de cada motor.
- Fechas y marcas de tiempo se guardan como texto ISO 8601.
- Los booleanos se guardan como INTEGER 0/1.
"""

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS centros (
        id {PK},
        nombre TEXT NOT NULL,
        regional TEXT,
        distrito TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS usuarios (
        id {PK},
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        nombre TEXT NOT NULL,
        cargo TEXT NOT NULL DEFAULT 'Docente Titular',
        nivel TEXT NOT NULL DEFAULT 'Secundaria',
        activo INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS anios_lectivos (
        id {PK},
        nombre TEXT NOT NULL UNIQUE,
        activo INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS periodos (
        id {PK},
        anio_id INTEGER NOT NULL REFERENCES anios_lectivos(id) ON DELETE CASCADE,
        numero INTEGER NOT NULL,
        nombre TEXT NOT NULL,
        estado TEXT NOT NULL DEFAULT 'programado',
        meta DOUBLE PRECISION,
        UNIQUE (anio_id, numero)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS areas (
        id {PK},
        nombre TEXT NOT NULL UNIQUE,
        nombre_largo TEXT,
        categoria TEXT NOT NULL,
        icono TEXT NOT NULL,
        estilo TEXT NOT NULL,
        orden INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS secciones (
        id {PK},
        anio_id INTEGER NOT NULL REFERENCES anios_lectivos(id) ON DELETE CASCADE,
        centro_id INTEGER NOT NULL REFERENCES centros(id),
        grado TEXT NOT NULL,
        grado_nombre TEXT NOT NULL,
        letra TEXT NOT NULL,
        modalidad TEXT NOT NULL DEFAULT 'Secundaria General',
        tutor_id INTEGER REFERENCES usuarios(id),
        UNIQUE (anio_id, centro_id, grado, letra)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cargas (
        id {PK},
        docente_id INTEGER NOT NULL REFERENCES usuarios(id),
        seccion_id INTEGER NOT NULL REFERENCES secciones(id) ON DELETE CASCADE,
        area_id INTEGER NOT NULL REFERENCES areas(id),
        UNIQUE (seccion_id, area_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS estudiantes (
        id {PK},
        matricula TEXT NOT NULL UNIQUE,
        rne TEXT,
        nombres TEXT NOT NULL,
        apellidos TEXT NOT NULL,
        activo INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inscripciones (
        id {PK},
        estudiante_id INTEGER NOT NULL REFERENCES estudiantes(id) ON DELETE CASCADE,
        seccion_id INTEGER NOT NULL REFERENCES secciones(id) ON DELETE CASCADE,
        condicion TEXT NOT NULL DEFAULT 'Regular',
        estado_acompanamiento TEXT,
        UNIQUE (estudiante_id, seccion_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluaciones (
        id {PK},
        carga_id INTEGER NOT NULL REFERENCES cargas(id) ON DELETE CASCADE,
        periodo_id INTEGER NOT NULL REFERENCES periodos(id) ON DELETE CASCADE,
        nombre TEXT NOT NULL,
        tipo TEXT NOT NULL,
        competencia TEXT,
        fecha TEXT,
        max_puntaje DOUBLE PRECISION NOT NULL DEFAULT 100,
        peso DOUBLE PRECISION NOT NULL,
        indicadores TEXT,
        created_by INTEGER REFERENCES usuarios(id),
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS calificaciones (
        id {PK},
        evaluacion_id INTEGER NOT NULL REFERENCES evaluaciones(id) ON DELETE CASCADE,
        inscripcion_id INTEGER NOT NULL REFERENCES inscripciones(id) ON DELETE CASCADE,
        puntaje DOUBLE PRECISION,
        updated_by INTEGER REFERENCES usuarios(id),
        updated_at TEXT NOT NULL,
        UNIQUE (evaluacion_id, inscripcion_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS observaciones (
        id {PK},
        inscripcion_id INTEGER NOT NULL REFERENCES inscripciones(id) ON DELETE CASCADE,
        periodo_id INTEGER REFERENCES periodos(id) ON DELETE SET NULL,
        tipo TEXT NOT NULL,
        aspecto TEXT,
        descripcion TEXT NOT NULL,
        autor_id INTEGER NOT NULL REFERENCES usuarios(id),
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_cargas_docente ON cargas (docente_id)",
    "CREATE INDEX IF NOT EXISTS ix_insc_seccion ON inscripciones (seccion_id)",
    "CREATE INDEX IF NOT EXISTS ix_eval_carga_periodo ON evaluaciones (carga_id, periodo_id)",
    "CREATE INDEX IF NOT EXISTS ix_calif_insc ON calificaciones (inscripcion_id)",
    "CREATE INDEX IF NOT EXISTS ix_obs_insc ON observaciones (inscripcion_id)",
]
