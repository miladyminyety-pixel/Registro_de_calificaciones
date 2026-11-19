# Registro de Calificaciones

Portal docente (MINERD · República Dominicana) para registrar evaluaciones y calificaciones, calcular promedios por período y dar seguimiento a estudiantes en riesgo. Backend en **Flask**, base de datos **PostgreSQL** (producción) o **SQLite** (desarrollo), y el frontend diseñado en Stitch convertido en plantillas conectadas a la API.

## Pantallas

| Ruta | Contenido |
|---|---|
| `/dashboard` | KPIs, promedio por área, distribución de literales, evolución por período, estudiantes en alerta |
| `/areas` | Áreas curriculares con promedio, evaluaciones y pendientes |
| `/registro` | Matriz de calificaciones editable (cálculo en vivo y guardado) |
| `/estudiantes`, `/estudiantes/<id>` | Búsqueda y ficha: histórico, diagnóstico y bitácora de acompañamiento |
| `/evaluaciones`, `/evaluaciones/nueva` | Instrumentos por área/sección y creación con control del 100 % |
| `/importar` | Carga de secciones y estudiantes desde Excel/CSV con vista previa (plantillas descargables) |
| `/mis-secciones`, `/configuracion`, `/acerca` | Secciones, cambio de contraseña, información |

`/reportes` (boletines imprimibles) aún no está implementado.

## Importar estudiantes

En **Importar Estudiantes** descarga la plantilla (Excel o CSV), complétala (`matricula`, `rne`, `nombres`, `apellidos`, `grado`, `seccion`, `condicion`) y súbela. Verás una vista previa con errores y avisos antes de confirmar; nada se guarda hasta entonces. Las secciones inexistentes se crean, un estudiante con matrícula ya registrada no se duplica y todo se guarda en una sola transacción. Máximo 2 MB y 2000 filas por archivo.

## Reglas de calificación

- Escala: **A** 90-100 · **B** 80-89 · **C** 70-79 · **D** < 70. Mínimo aprobatorio: 70.
- Cada evaluación aporta `puntaje ÷ máximo × peso`. El promedio del período se calcula sobre el **peso ya calificado**, así que a mitad de período refleja el desempeño real.
- Las ponderaciones de un área en un período no pueden superar el 100 %.
- Los períodos cerrados son de solo lectura.

## Desarrollo local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # edita usuario y clave
flask --app wsgi run --debug  # http://localhost:5000
pytest                        # 82 pruebas
```

Sin `DATABASE_URL` usa SQLite en `instance/registro.db`. Con `SEED_DEMO_DATA=true` carga 40 estudiantes y notas de ejemplo (solo si la base está vacía).

## Despliegue en Render

1. En [Render](https://dashboard.render.com): **New → Blueprint** y elige este repositorio. Lee `render.yaml`.
2. Render te pedirá `ADMIN_USERNAME`, `ADMIN_PASSWORD` (mínimo 8 caracteres) y `ADMIN_NAME`. Con ellos se crea tu usuario en el primer arranque.
3. **Apply**. Espera a que termine el build; la URL queda en el panel del servicio.
4. Entra con tu usuario y cambia la contraseña en **Configuración** si lo deseas.

Variables: `SECRET_KEY` (se genera sola), `DATABASE_URL` (viene de la base), `SEED_DEMO_DATA` (`false` por defecto).

### Límites del plan gratuito (importante)

- **La base de datos gratuita expira a los 30 días** y, tras 14 días de gracia, Render borra los datos. Para calificaciones reales pasa la base a un plan de pago antes de ese plazo (Dashboard → la base → *Upgrade*).
- El servicio gratuito se duerme tras 15 minutos sin tráfico; el primer acceso tarda cerca de un minuto.
- La base gratuita no tiene copias de seguridad.

## Seguridad

Contraseñas con hash (scrypt), sesiones con cookie `HttpOnly`/`Secure`/`SameSite=Lax`, protección CSRF en todo lo que modifica datos, bloqueo temporal tras 5 intentos fallidos de acceso, validación estricta de calificaciones y comprobación de que cada docente solo accede a sus propias secciones. El bloqueo de intentos vive en memoria de cada proceso: frena fuerza bruta básica pero no sustituye a un firewall.

## Estructura

```
app/            Aplicación Flask (config, db, schema, grading, builders, actions, routes/)
app/templates/  Pantallas del frontend (Tailwind + Material Symbols, como en el diseño)
tests/          Pruebas unitarias, de páginas y de la API
wsgi.py         Entrada para gunicorn
render.yaml     Blueprint de Render (servicio web + PostgreSQL)
```

El frontend carga Tailwind desde su CDN, tal como lo generó Stitch.
