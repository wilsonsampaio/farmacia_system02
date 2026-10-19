"""Histórico de vendas, detalhe, impressão do cupom e cancelamento."""
from flask import (Blueprint, abort, flash, g, jsonify, redirect, render_template,
                   request, url_for)

from ..db import get_db, paginate, todos, um
from ..security import login_required, pode, registrar_acao
from ..services import ErroNegocio, cancelar_venda
from ..utils import FORMAS_PAGAMENTO

bp = Blueprint("vendas", __name__, url_prefix="/vendas")


@bp.route("/")
@login_required("vendas")
def lista():
    db = get_db()
    filtros = ["1=1"]
    params = []
    termo = (request.args.get("q") or "").strip()
    if termo:
        filtros.append("(v.numero LIKE ? OR c.nome LIKE ? OR u.nome LIKE ?)")
        like = f"%{termo}%"
        params += [like, like, like]
    if request.args.get("de"):
        filtros.append("date(v.data) >= date(?)")
        params.append(request.args.get("de"))
    if request.args.get("ate"):
        filtros.append("date(v.data) <= date(?)")
        params.append(request.args.get("ate"))
    if request.args.get("forma"):
        filtros.append("v.forma_pagamento = ?")
        params.append(request.args.get("forma"))
    if request.args.get("status"):
        filtros.append("v.status = ?")
        params.append(request.args.get("status"))
    if request.args.get("operador"):
        filtros.append("v.usuario_id = ?")
        params.append(request.args.get("operador"))

    sql = f"""SELECT v.*, c.nome AS cliente, u.nome AS operador,
                     (SELECT COUNT(*) FROM venda_itens vi WHERE vi.venda_id = v.id) AS itens
              FROM vendas v LEFT JOIN clientes c ON c.id = v.cliente_id
              LEFT JOIN usuarios u ON u.id = v.usuario_id
              WHERE {' AND '.join(filtros)} ORDER BY v.id DESC"""
    page = request.args.get("page", 1, type=int)
    itens, total, pg, pages = paginate(sql, tuple(params), page, per_page=25)

    totais = db.execute(
        f"""SELECT COUNT(*) q, COALESCE(SUM(v.total),0) t FROM vendas v
            LEFT JOIN clientes c ON c.id=v.cliente_id LEFT JOIN usuarios u ON u.id=v.usuario_id
            WHERE v.status='concluida' AND {' AND '.join(filtros)}""", tuple(params)).fetchone()
    operadores = todos("SELECT id, nome FROM usuarios WHERE ativo=1 ORDER BY nome")
    return render_template("vendas/lista.html", itens=itens, total=total, page=pg, pages=pages,
                           termo=termo, formas=FORMAS_PAGAMENTO, operadores=operadores,
                           totais=totais, args=request.args)


@bp.route("/<int:venda_id>")
@login_required("vendas")
def detalhe(venda_id):
    venda = um("""SELECT v.*, c.nome AS cliente, c.cpf AS cliente_cpf, c.celular AS cliente_celular,
                         u.nome AS operador, us.nome AS cancelado_por_nome
                  FROM vendas v LEFT JOIN clientes c ON c.id=v.cliente_id
                  LEFT JOIN usuarios u ON u.id=v.usuario_id
                  LEFT JOIN usuarios us ON us.id=v.cancelada_por WHERE v.id=?""", (venda_id,))
    if venda is None:
        flash("Venda não encontrada.", "erro")
        return redirect(url_for("vendas.lista"))
    itens = todos("""SELECT vi.*, p.principio_ativo, p.laboratorio, p.tarja
                     FROM venda_itens vi LEFT JOIN produtos p ON p.id=vi.produto_id
                     WHERE vi.venda_id=?""", (venda_id,))
    pagamentos = todos("SELECT * FROM pagamentos WHERE venda_id=?", (venda_id,))
    ficha = um("SELECT * FROM fichas WHERE venda_id=? AND tipo='lancamento'", (venda_id,))
    return render_template("vendas/detalhe.html", venda=venda, itens=itens, pagamentos=pagamentos,
                           ficha=ficha, formas=FORMAS_PAGAMENTO)


@bp.route("/<int:venda_id>/cupom")
@login_required("vendas")
def cupom(venda_id):
    venda = um("""SELECT v.*, c.nome AS cliente, c.cpf AS cliente_cpf, c.celular AS cliente_celular,
                         u.nome AS operador
                  FROM vendas v LEFT JOIN clientes c ON c.id=v.cliente_id
                  LEFT JOIN usuarios u ON u.id=v.usuario_id WHERE v.id=?""", (venda_id,))
    if venda is None:
        abort(404)
    itens = todos("SELECT * FROM venda_itens WHERE venda_id=?", (venda_id,))
    pagamentos = todos("SELECT * FROM pagamentos WHERE venda_id=?", (venda_id,))
    largura = request.args.get("largura", "80")
    auto = request.args.get("auto", "1") == "1"
    if request.args.get("marcar") == "1":
        db = get_db()
        db.execute("UPDATE vendas SET cupom_impresso = cupom_impresso + 1 WHERE id = ?", (venda_id,))
        db.commit()
    from datetime import datetime
    return render_template("vendas/cupom.html", venda=venda, itens=itens, pagamentos=pagamentos,
                           largura=largura, auto_print=auto, params=request.args,
                           hora_impressao=datetime.now().strftime("%d/%m/%Y %H:%M"))


@bp.route("/<int:venda_id>/imprimir", methods=["POST"])
@login_required("vendas")
def imprimir(venda_id):
    db = get_db()
    db.execute("UPDATE vendas SET cupom_impresso = cupom_impresso + 1 WHERE id = ?", (venda_id,))
    db.commit()
    return jsonify({"ok": True, "url": url_for("vendas.cupom", venda_id=venda_id, auto=1)})


@bp.route("/<int:venda_id>/cancelar", methods=["POST"])
@login_required("vendas")
def cancelar(venda_id):
    venda = um("SELECT * FROM vendas WHERE id = ?", (venda_id,))
    if venda is None:
        flash("Venda não encontrada.", "erro")
        return redirect(url_for("vendas.lista"))
    usuario = g.get("usuario")
    if usuario["perfil"] == "caixa" and venda["usuario_id"] != usuario["id"]:
        flash("Operadores de caixa só podem cancelar vendas lançadas por eles.", "erro")
        return redirect(url_for("vendas.detalhe", venda_id=venda_id))
    motivo = (request.form.get("motivo") or "").strip() or "Cancelamento pelo operador"
    if request.form.get("confirmar") != venda["numero"]:
        flash("Digite o número da venda para confirmar o cancelamento.", "erro")
        return redirect(url_for("vendas.detalhe", venda_id=venda_id))
    try:
        cancelar_venda(venda_id, usuario, motivo)
        flash(f"Venda {venda['numero']} cancelada e mercadoria devolvida ao estoque.", "ok")
    except ErroNegocio as erro:
        flash(str(erro), "erro")
    return redirect(url_for("vendas.detalhe", venda_id=venda_id))


@bp.route("/api/<int:venda_id>/itens")
@login_required("vendas")
def api_itens(venda_id):
    itens = todos("SELECT * FROM venda_itens WHERE venda_id = ?", (venda_id,))
    return jsonify({"itens": [dict(i) for i in itens]})
