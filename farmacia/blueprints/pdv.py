"""PDV (Ponto de Venda) - tela de caixa, carrinho, pagamento e finalização."""
import json

from flask import (Blueprint, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)

from ..db import get_db, todos, um
from ..security import login_required, registrar_acao
from ..services import ErroNegocio, criar_venda
from ..utils import FORMAS_PAGAMENTO, brl, cpf_valido, digitos, mascara_cpf

bp = Blueprint("pdv", __name__, url_prefix="/pdv")


@bp.route("/")
@login_required("pdv")
def index():
    cliente_id = request.args.get("cliente", type=int)
    cliente = um("SELECT * FROM clientes WHERE id = ?", (cliente_id,)) if cliente_id else None
    ultimas = todos(
        """SELECT v.id, v.numero, v.data, v.total, v.status, u.nome AS operador, c.nome AS cliente
           FROM vendas v LEFT JOIN usuarios u ON u.id=v.usuario_id
           LEFT JOIN clientes c ON c.id=v.cliente_id
           ORDER BY v.id DESC LIMIT 10""")
    formas = FORMAS_PAGAMENTO
    return render_template("pdv/index.html", cliente=cliente, ultimas=ultimas,
                           formas=formas, terminal=session.get("terminal", "PDV"))


@bp.route("/buscar")
@login_required("pdv")
def buscar():
    """Busca por código de barras exata (leitor) com fallback por nome."""
    termo = (request.args.get("codigo") or "").strip()
    if not termo:
        return jsonify({"produto": None, "resultados": []})
    limpo = digitos(termo)
    produto = None
    if limpo:
        produto = um("""SELECT p.*, (SELECT arquivo FROM produto_fotos f WHERE f.produto_id=p.id
                        ORDER BY principal DESC, id LIMIT 1) AS foto
                        FROM produtos p WHERE p.ativo=1 AND (p.ean = ? OR p.codigo = ?)""",
                     (limpo, termo))
    if produto is None:
        produto = um("""SELECT p.*, (SELECT arquivo FROM produto_fotos f WHERE f.produto_id=p.id
                        ORDER BY principal DESC, id LIMIT 1) AS foto
                        FROM produtos p WHERE p.ativo=1 AND p.codigo = ? COLLATE NOCASE""",
                     (termo,))
    if produto:
        return jsonify({"produto": dict(produto), "resultados": []})
    like = f"%{termo}%"
    resultados = todos(
        """SELECT p.id, p.codigo, p.ean, p.nome, p.principio_ativo, p.laboratorio, p.apresentacao,
                  p.tarja, p.preco_venda, p.estoque, p.unidade,
                  (SELECT arquivo FROM produto_fotos f WHERE f.produto_id=p.id
                   ORDER BY principal DESC, id LIMIT 1) AS foto
           FROM produtos p WHERE p.ativo=1 AND (p.nome LIKE ? OR p.principio_ativo LIKE ?
                                                OR p.codigo LIKE ? OR p.ean LIKE ?)
           ORDER BY p.nome COLLATE NOCASE LIMIT 40""", (like, like, like, like))
    return jsonify({"produto": None, "resultados": [dict(r) for r in resultados]})


@bp.route("/venda", methods=["POST"])
@login_required("pdv")
def finalizar():
    payload = request.get_json(silent=True) or {}
    dados = {
        "cliente_id": payload.get("cliente_id") or request.form.get("cliente_id") or None,
        "itens": payload.get("itens") or [],
        "desconto": payload.get("desconto") or 0,
        "pagamentos": payload.get("pagamentos") or [],
        "terminal": payload.get("terminal") or session.get("terminal"),
        "observacao": payload.get("observacao") or "",
    }
    try:
        dados["cliente_id"] = int(dados["cliente_id"]) if dados["cliente_id"] else None
    except (TypeError, ValueError):
        dados["cliente_id"] = None
    try:
        resultado = criar_venda(dados, g.get("usuario"))
    except ErroNegocio as erro:
        return jsonify({"erro": str(erro)}), 400
    except Exception as erro:  # noqa: BLE001
        get_db().rollback()
        return jsonify({"erro": f"Falha ao registrar a venda: {erro}"}), 500

    resultado["cupom"] = url_for("vendas.cupom", venda_id=resultado["id"])
    resultado["detalhe"] = url_for("vendas.detalhe", venda_id=resultado["id"])
    return jsonify(resultado), 201


@bp.route("/cliente", methods=["POST"])
@login_required("pdv")
def cliente_rapido():
    """Cadastro rápido de cliente dentro do PDV (para venda na ficha)."""
    payload = request.get_json(silent=True) or {}
    nome = (payload.get("nome") or "").strip()
    doc = digitos(payload.get("cpf") or "")
    if len(nome) < 3:
        return jsonify({"erro": "Informe o nome completo do cliente."}), 400
    if doc and len(doc) != 11:
        return jsonify({"erro": "CPF deve ter 11 dígitos (ou deixe em branco)."}), 400
    if doc:
        from ..utils import cpf_valido as _valida
        if not _valida(doc):
            return jsonify({"erro": "CPF inválido."}), 400
        if um("SELECT id FROM clientes WHERE cpf = ?", (mascara_cpf(doc),)):
            return jsonify({"erro": "Já existe cliente com este CPF."}), 400
    from ..db import inserir
    cliente_id = inserir("clientes", {
        "nome": nome,
        "cpf": mascara_cpf(doc) if doc else None,
        "celular": (payload.get("celular") or "").strip() or None,
        "limite_credito": 0.0,
    })
    registrar_acao("cliente_rapido", "clientes", cliente_id, f"Cadastro rápido no PDV: {nome}")
    return jsonify({"ok": True, "cliente": dict(um("SELECT * FROM clientes WHERE id = ?", (cliente_id,)))}), 201


@bp.route("/forma-pagamento")
@login_required("pdv")
def formas_pagamento():
    return jsonify({"formas": [{"codigo": c, "nome": n} for c, n in FORMAS_PAGAMENTO]})


@bp.route("/cliente/<int:cliente_id>/fiado")
@login_required("pdv")
def fiado(cliente_id):
    cliente = um("SELECT id, nome, cpf, saldo_credito, limite_credito FROM clientes WHERE id = ?", (cliente_id,))
    if not cliente:
        return jsonify({"erro": "Cliente não encontrado."}), 404
    aberto = um("""SELECT COALESCE(SUM(valor),0) FROM fichas WHERE cliente_id=? AND tipo='lancamento'""",
                (cliente_id,))[0]
    pago = um("""SELECT COALESCE(SUM(-valor),0) FROM fichas WHERE cliente_id=? AND tipo='pagamento'""",
              (cliente_id,))[0]
    return jsonify({"cliente": dict(cliente), "lancado": round(aberto, 2), "pago": round(pago, 2),
                    "disponivel": round(float(cliente["limite_credito"] or 0) - float(cliente["saldo_credito"] or 0), 2)})
