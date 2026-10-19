"""Rotas auxiliares: servir arquivos enviados (fotos de produtos e logotipos)."""
import os

from flask import Blueprint, abort, current_app, send_from_directory, session, url_for

bp = Blueprint("views", __name__)

SUBPASTAS_PERMITIDAS = ("produtos", "empresa")


def media_url(nome, subpasta="produtos"):
    """URL pública de um arquivo enviado (usado nos templates Jinja)."""
    if not nome:
        return None
    return url_for("views.media", subpasta=subpasta, arquivo=nome)


@bp.route("/media/<subpasta>/<path:arquivo>")
def media(subpasta, arquivo):
    if not session.get("usuario_id"):
        abort(403)
    if subpasta not in SUBPASTAS_PERMITIDAS:
        abort(404)
    base = os.path.join(current_app.config["UPLOAD_DIR"], subpasta)
    if not os.path.isdir(base):
        abort(404)
    return send_from_directory(base, arquivo, max_age=3600)
