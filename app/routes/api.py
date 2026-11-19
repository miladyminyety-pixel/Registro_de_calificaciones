"""API JSON (la usa el frontend; también sirve para integraciones)."""
from flask import Blueprint, jsonify, request, session

from .. import actions, builders
from ..data import resolver_contexto
from ..db import get_db
from ..errors import ApiError, invalid
from ..security import current_user, login_required

bp = Blueprint("api", __name__, url_prefix="/api")


def _json() -> dict | list:
    cuerpo = request.get_json(silent=True)
    if cuerpo is None:
        raise invalid("Se esperaba un cuerpo JSON")
    return cuerpo


def _ctx():
    return resolver_contexto(get_db(), session.get("anio_id"), session.get("periodo_id"))


@bp.get("/me")
@login_required
def me():
    return jsonify(current_user())


@bp.get("/dashboard")
@login_required
def dashboard():
    seccion = request.args.get("seccion", type=int)
    return jsonify(builders.dashboard(get_db(), current_user(), _ctx(), seccion))


@bp.get("/areas")
@login_required
def areas():
    return jsonify(builders.areas_resumen(get_db(), current_user(), _ctx(), request.args.get("seccion", type=int)))


@bp.get("/cargas/<int:carga_id>/matriz")
@login_required
def matriz(carga_id: int):
    ctx = _ctx()
    periodo_id = request.args.get("periodo", type=int) or (ctx["periodo"]["id"] if ctx["periodo"] else None)
    if periodo_id is None:
        raise invalid("No hay período activo", "periodo")
    return jsonify(builders.matriz(get_db(), current_user(), carga_id, periodo_id))


@bp.put("/cargas/<int:carga_id>/calificaciones")
@login_required
def guardar(carga_id: int):
    cuerpo = _json()
    cambios = cuerpo.get("cambios") if isinstance(cuerpo, dict) else None
    return jsonify(actions.guardar_calificaciones(get_db(), current_user(), carga_id, cambios))


@bp.get("/cargas/<int:carga_id>/periodos/<int:periodo_id>/balance")
@login_required
def balance(carga_id: int, periodo_id: int):
    return jsonify(actions.balance(get_db(), current_user(), carga_id, periodo_id))


@bp.post("/evaluaciones")
@login_required
def crear_evaluacion():
    return jsonify(actions.crear_evaluaciones(get_db(), current_user(), _json())), 201


@bp.delete("/evaluaciones/<int:evaluacion_id>")
@login_required
def eliminar_evaluacion(evaluacion_id: int):
    return jsonify(actions.eliminar_evaluacion(get_db(), current_user(), evaluacion_id))


@bp.get("/estudiantes/<int:insc_id>")
@login_required
def perfil(insc_id: int):
    return jsonify(builders.perfil(get_db(), current_user(), insc_id, _ctx()))


@bp.post("/estudiantes/<int:insc_id>/observaciones")
@login_required
def observacion(insc_id: int):
    ctx = _ctx()
    periodo_id = ctx["periodo"]["id"] if ctx["periodo"] else None
    return jsonify(actions.crear_observacion(get_db(), current_user(), insc_id, _json(), periodo_id)), 201


@bp.errorhandler(ApiError)
def _api_error(exc: ApiError):
    return jsonify(exc.to_dict()), exc.status
