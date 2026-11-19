from flask import Blueprint, redirect, render_template, request, session, url_for

from .. import actions, builders, grading
from ..data import Datos, cargas_docente, resolver_contexto, secciones_docente
from ..db import get_db
from ..errors import not_found
from ..security import current_user, login_required, safe_next

bp = Blueprint("pages", __name__)


def _int(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _ctx():
    return resolver_contexto(get_db(), session.get("anio_id"), session.get("periodo_id"))


@bp.get("/")
def inicio():
    return redirect(url_for("pages.dashboard"))


@bp.get("/contexto")
@login_required
def cambiar_contexto():
    """Cambia año lectivo / período de la sesión (selectores de la barra superior)."""
    db = get_db()
    anio_id = _int(request.args.get("anio"))
    periodo_id = _int(request.args.get("periodo"))
    if anio_id is not None and anio_id != session.get("anio_id"):
        session["anio_id"] = anio_id
        session.pop("periodo_id", None)  # los períodos pertenecen al año
    if periodo_id is not None:
        ctx = resolver_contexto(db, session.get("anio_id"), periodo_id)
        if ctx["periodo"] and ctx["periodo"]["id"] == periodo_id:
            session["periodo_id"] = periodo_id
    destino = request.args.get("next")
    # al cambiar de año se descarta la carga/sección concreta de la URL anterior
    if destino and "?" in destino:
        destino = destino.split("?")[0]
    return redirect(safe_next(destino))


@bp.get("/dashboard")
@login_required
def dashboard():
    user, ctx = current_user(), _ctx()
    datos = builders.dashboard(get_db(), user, ctx, _int(request.args.get("seccion")))
    return render_template("dashboard.html", d=datos, nav="dashboard")


@bp.get("/mis-secciones")
@login_required
def mis_secciones():
    user, ctx = current_user(), _ctx()
    db = get_db()
    secciones = secciones_docente(db, user["id"], ctx["anio"]["id"]) if ctx["anio"] else []
    cargas = cargas_docente(db, user["id"], ctx["anio"]["id"]) if ctx["anio"] else []
    datos = Datos(db, cargas, [ctx["periodo"]["id"]] if ctx["periodo"] else [])
    for s in secciones:
        s["estudiantes"] = len(datos.inscs.get(s["id"], []))
        s["cargas"] = [c for c in cargas if c["seccion_id"] == s["id"]]
    return render_template("secciones.html", secciones=secciones, nav="mis-secciones")


@bp.get("/areas")
@login_required
def areas():
    user, ctx = current_user(), _ctx()
    datos = builders.areas_resumen(get_db(), user, ctx, _int(request.args.get("seccion")))
    return render_template("areas.html", d=datos, nav="areas-curriculares")


@bp.get("/registro")
@login_required
def registro():
    user, ctx = current_user(), _ctx()
    db = get_db()
    if not ctx["anio"] or not ctx["periodo"]:
        return render_template("registro.html", m=None, cargas=[], nav="registro-de-calificaciones")
    cargas = cargas_docente(db, user["id"], ctx["anio"]["id"])
    carga_id = _int(request.args.get("carga"))
    if carga_id is None and cargas:
        carga_id = cargas[0]["id"]
    matriz = None
    if carga_id is not None:
        matriz = builders.matriz(db, user, carga_id, ctx["periodo"]["id"])
    return render_template("registro.html", m=matriz, cargas=cargas, nav="registro-de-calificaciones")


@bp.get("/estudiantes")
@login_required
def estudiantes():
    user, ctx = current_user(), _ctx()
    datos = builders.estudiantes(
        get_db(), user, ctx, q=(request.args.get("q") or "")[:80],
        seccion_id=_int(request.args.get("seccion")), solo_alerta=request.args.get("alerta") == "1")
    return render_template("estudiantes.html", d=datos, nav="estudiantes")


@bp.get("/estudiantes/<int:insc_id>")
@login_required
def perfil(insc_id: int):
    user, ctx = current_user(), _ctx()
    datos = builders.perfil(get_db(), user, insc_id, ctx)
    return render_template("perfil.html", p=datos, tipos=grading.TIPOS_OBSERVACION, nav="estudiantes")


@bp.get("/evaluaciones")
@login_required
def evaluaciones():
    user, ctx = current_user(), _ctx()
    datos = builders.evaluaciones_lista(get_db(), user, ctx)
    return render_template("evaluaciones.html", d=datos, nav="evaluaciones")


@bp.get("/evaluaciones/nueva")
@login_required
def evaluacion_nueva():
    user, ctx = current_user(), _ctx()
    db = get_db()
    if not ctx["anio"] or not ctx["periodo"]:
        raise not_found("No hay un año lectivo configurado")
    cargas = cargas_docente(db, user["id"], ctx["anio"]["id"])
    preseleccion = _int(request.args.get("carga"))
    return render_template(
        "evaluacion_nueva.html", cargas=cargas, preseleccion=preseleccion,
        tipos=grading.TIPOS_EVALUACION, competencias=grading.COMPETENCIAS_FUNDAMENTALES,
        nav="evaluaciones")


@bp.route("/configuracion", methods=["GET", "POST"])
@login_required
def configuracion():
    user = current_user()
    mensaje = error = campo = None
    if request.method == "POST":
        try:
            if request.form.get("nueva") != request.form.get("confirmar"):
                raise actions.invalid("Las contraseñas nuevas no coinciden", "confirmar")
            actions.cambiar_password(get_db(), user, request.form.get("actual"), request.form.get("nueva"))
            mensaje = "Contraseña actualizada correctamente."
        except actions.ApiError as exc:
            error, campo = exc.message, exc.field
    return render_template("configuracion.html", mensaje=mensaje, error=error, campo=campo,
                           nav="configuracion")


@bp.get("/reportes")
@login_required
def reportes():
    return render_template("proximamente.html", titulo="Reportes Académicos", nav="reportes-academicos",
                           texto="Los reportes imprimibles (boletín por estudiante y consolidado por sección) "
                                 "aún no están disponibles en esta versión.")


@bp.get("/acerca")
@login_required
def acerca():
    return render_template("acerca.html", nav="acerca-de-la-aplicacion")
