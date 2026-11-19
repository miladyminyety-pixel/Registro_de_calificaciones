"""Datos iniciales.

- ``seed_base``: catálogo imprescindible (áreas, año lectivo, períodos). Siempre.
- ``crear_admin``: usuario inicial desde variables de entorno (solo si no hay usuarios).
- ``seed_demo``: datos de demostración (solo si la base está vacía y se pide).
"""
from __future__ import annotations

from . import grading
from .db import Conn, utcnow
from .security import hash_password

# nombre, nombre_largo, categoría, icono, estilo (clases del diseño), orden
AREAS = [
    ("Lengua Española", None, "Área Fundamental", "translate", "esp", 1),
    ("Matemática", None, "Área Fundamental", "calculate", "mat", 2),
    ("Ciencias Sociales", None, "Área Fundamental", "public", "soc", 3),
    ("Ciencias de la Naturaleza", None, "Área Fundamental", "biotech", "nat", 4),
    ("Inglés", "Lenguas Extranjeras (Inglés)", "Lenguas Extranjeras", "language", "ing", 5),
    ("Educación Física", None, "Desarrollo Motor", "sports_soccer", "fis", 6),
    ("Educación Artística", None, "Expresión Creativa", "palette", "art", 7),
    ("F.I.H.R.", "Formación Integral Humana y Religiosa (F.I.H.R.)", "Valores y Ética", "diversity_3", "fihr", 8),
]

PERIODOS = [
    (1, "1er Período (P1)"),
    (2, "2do Período (P2)"),
    (3, "3er Período (P3)"),
    (4, "4to Período (P4)"),
]


def seed_base(db: Conn) -> None:
    for nombre, largo, categoria, icono, estilo, orden in AREAS:
        if not db.scalar("SELECT 1 FROM areas WHERE nombre = ?", (nombre,)):
            db.execute(
                "INSERT INTO areas (nombre, nombre_largo, categoria, icono, estilo, orden) VALUES (?,?,?,?,?,?)",
                (nombre, largo, categoria, icono, estilo, orden),
            )
    if not db.scalar("SELECT COUNT(*) FROM anios_lectivos"):
        for nombre, activo in (("2025-2026", 1), ("2024-2025", 0)):
            anio_id = db.insert("INSERT INTO anios_lectivos (nombre, activo) VALUES (?, ?)", (nombre, activo))
            for numero, etiqueta in PERIODOS:
                if activo:
                    estado = "en_curso" if numero == 1 else "programado"
                else:
                    estado = "cerrado"
                db.execute(
                    "INSERT INTO periodos (anio_id, numero, nombre, estado) VALUES (?,?,?,?)",
                    (anio_id, numero, etiqueta, estado),
                )
    db.commit()


def crear_admin(db: Conn, username: str, password: str, nombre: str) -> bool:
    if db.scalar("SELECT COUNT(*) FROM usuarios"):
        return False
    if not username or len(password) < 8:
        return False
    db.execute(
        "INSERT INTO usuarios (username, password_hash, nombre, cargo, nivel, activo, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (username.strip().lower(), hash_password(password), nombre, "Docente Titular", "Secundaria", 1, utcnow()),
    )
    db.commit()
    return True


# --------------------------------------------------------------------- demo
# (matrícula, RNE, nombres, apellidos, sección, [prácticos, pruebas, participación, proyecto])
_DEMO_5A = [
    ("MAT-2025-0112", "10492812", "María", "Fernández", [19, 28, 10, 38]),
    ("MAT-2025-0104", "10492804", "José Antonio", "Pérez", [14, 19, 7, 28]),
    ("MAT-2025-0215", "10492915", "Ana", "Martínez", [18, 25, 9, 36]),
    ("MAT-2025-0418", "CR-0810-0418", "Carlos", "Rodríguez", [12, 18, 6, 28]),
    ("MAT-2025-0522", "10493122", "Daniela", "Ramírez", [16, 22, 8, 31]),
    ("MAT-2025-0630", "10493230", "Luis Miguel", "Santos", [17, 24, 9, 35]),
]
_NOMBRES = ["Sofía", "Mateo", "Valentina", "Santiago", "Camila", "Diego", "Isabella", "Samuel",
            "Lucía", "Gabriel", "Paola", "Andrés", "Natalia", "Emilio", "Fabiola", "Rafael"]
_APELLIDOS = ["García", "Núñez", "Peña", "Jiménez", "Reyes", "Castillo", "Medina", "Almonte",
              "Taveras", "Báez", "Cabrera", "Guzmán", "Vargas", "Polanco", "Sánchez", "De la Cruz"]

# Tipos de evaluación de la matriz del diseño: (nombre, tipo, peso, máximo)
_EVALS_MATRIZ = [
    ("Trabajos Prácticos", "trabajo_practico", 20, 20),
    ("Pruebas Escritas", "prueba_escrita", 30, 30),
    ("Participación", "participacion", 10, 10),
    ("Proyecto Integrador", "proyecto_integrador", 40, 40),
]


def _variar(base: list[int], delta: int) -> list[int]:
    topes = [20, 30, 10, 40]
    return [max(0, min(t, v + delta)) for v, t in zip(base, topes)]


def seed_demo(db: Conn, docente_id: int) -> bool:
    """Carga un centro, 3 secciones y estudiantes con calificaciones de ejemplo."""
    if db.scalar("SELECT COUNT(*) FROM estudiantes"):
        return False
    anio = db.one("SELECT id FROM anios_lectivos WHERE activo = 1")
    p1 = db.one("SELECT id FROM periodos WHERE anio_id = ? AND numero = 1", (anio["id"],))
    centro_id = db.insert(
        "INSERT INTO centros (nombre, regional, distrito) VALUES (?,?,?)",
        ("Centro Educativo Politécnico Víctor Estrella Liz", "Regional 15", "Distrito 02"),
    )
    areas = {a["nombre"]: a["id"] for a in db.query("SELECT id, nombre FROM areas")}
    ahora = utcnow()

    secciones = {}
    for letra in ("A", "B", "C"):
        secciones[letra] = db.insert(
            "INSERT INTO secciones (anio_id, centro_id, grado, grado_nombre, letra, modalidad, tutor_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (anio["id"], centro_id, "5to", "5to Secundaria", letra, "Secundaria General",
             docente_id if letra == "A" else None),
        )

    # Qué áreas imparte en cada sección (según "Mis áreas y secciones")
    reparto = {
        "Lengua Española": "ABC", "Matemática": "AB", "Ciencias Sociales": "AC",
        "Ciencias de la Naturaleza": "ABC", "Inglés": "AB", "Educación Física": "ABC",
        "Educación Artística": "BC", "F.I.H.R.": "ABC",
    }
    cargas: dict[tuple[str, str], int] = {}
    for area, letras in reparto.items():
        for letra in letras:
            cargas[(area, letra)] = db.insert(
                "INSERT INTO cargas (docente_id, seccion_id, area_id) VALUES (?,?,?)",
                (docente_id, secciones[letra], areas[area]),
            )

    # Estudiantes: los 6 del diseño en 5to A y un grupo adicional en cada sección
    estudiantes: dict[str, list[tuple[int, list[int]]]] = {"A": [], "B": [], "C": []}
    contador = 1000

    def nuevo(matricula, rne, nombres, apellidos, letra, notas, acompanamiento=None, condicion="Regular"):
        est_id = db.insert(
            "INSERT INTO estudiantes (matricula, rne, nombres, apellidos, activo, created_at) VALUES (?,?,?,?,1,?)",
            (matricula, rne, nombres, apellidos, ahora),
        )
        insc_id = db.insert(
            "INSERT INTO inscripciones (estudiante_id, seccion_id, condicion, estado_acompanamiento) VALUES (?,?,?,?)",
            (est_id, secciones[letra], condicion, acompanamiento),
        )
        estudiantes[letra].append((insc_id, notas))

    for mat, rne, nom, ape, notas in _DEMO_5A:
        acomp = {"MAT-2025-0418": "En riesgo académico", "MAT-2025-0522": "Seguimiento",
                 "MAT-2025-0104": "Plan de apoyo", "MAT-2025-0630": "Tutoría activa"}.get(mat)
        nuevo(mat, rne, nom, ape, "A", notas, acomp)

    for letra, cantidad in (("A", 10), ("B", 12), ("C", 12)):
        for k in range(cantidad):
            contador += 1
            base = _DEMO_5A[(k + (0 if letra == "A" else 2 if letra == "B" else 4)) % 6][4]
            delta = (k % 5) - 2
            nuevo(f"MAT-2025-{contador}", f"1049{contador}", _NOMBRES[(k + ord(letra)) % len(_NOMBRES)],
                  _APELLIDOS[(k * 3 + ord(letra)) % len(_APELLIDOS)], letra, _variar(base, delta))

    # Evaluaciones y calificaciones. Matemática 5to A usa la matriz exacta del diseño.
    for (area, letra), carga_id in cargas.items():
        ajuste = {"Matemática": -4, "Educación Física": 6, "Educación Artística": 5, "F.I.H.R.": 6}.get(area, 0)
        for nombre, tipo, peso, maximo in _EVALS_MATRIZ:
            eval_id = db.insert(
                """
                INSERT INTO evaluaciones (carga_id, periodo_id, nombre, tipo, fecha, max_puntaje, peso,
                                          created_by, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (carga_id, p1["id"], nombre, tipo, "2025-10-15", maximo, peso, docente_id, ahora),
            )
            col = [e[0] for e in _EVALS_MATRIZ].index(nombre)
            filas = []
            for insc_id, notas in estudiantes[letra]:
                es_demo_exacto = area == "Matemática" and letra == "A"
                valor = notas[col] if (es_demo_exacto or ajuste == 0) else max(
                    0, min(maximo, round(notas[col] + ajuste * maximo / 100)))
                if area == "Matemática" and letra != "A":
                    valor = max(0, min(maximo, round(notas[col] - 1)))
                filas.append((eval_id, insc_id, float(valor), docente_id, ahora))
            db.executemany(
                "INSERT INTO calificaciones (evaluacion_id, inscripcion_id, puntaje, updated_by, updated_at) "
                "VALUES (?,?,?,?,?)",
                filas,
            )

    # Observaciones del expediente de Carlos Rodríguez (como en el diseño)
    carlos = db.one("SELECT i.id FROM inscripciones i JOIN estudiantes e ON e.id = i.estudiante_id "
                    "WHERE e.matricula = 'MAT-2025-0418'")
    for tipo, aspecto, texto, fecha in (
        ("dificultad", "Matemática",
         "Dificultad recurrente en la prueba escrita parcial de matemática. Buena disposición y "
         "participación en proyectos colaborativos.", "2025-09-28T12:00:00Z"),
        ("estrategia_recuperacion", "Matemática",
         "Se aplicó plan de tutoría en resolución de ecuaciones de primer grado. Asignadas prácticas "
         "guiadas y seguimiento los miércoles en contraturno.", "2025-10-14T12:00:00Z"),
    ):
        db.execute(
            "INSERT INTO observaciones (inscripcion_id, periodo_id, tipo, aspecto, descripcion, autor_id, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (carlos["id"], p1["id"], tipo, aspecto, texto, docente_id, fecha),
        )
    db.commit()
    return True


def _assert_escala() -> None:  # pragma: no cover - sanity check al importar en desarrollo
    assert grading.literal_de(95) == "A"
