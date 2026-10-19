"""Cadastro de fornecedores e histórico de notas de entrada."""
from flask import (Blueprint, flash, jsonify, redirect, render_template, request, url_for)

from ..db import agora, atualizar, get_db, inserir, paginate, todos, um
from ..security import login_required, registrar_acao
from ..utils import cnpj_valido, mascara_cnpj

bp = Blueprint("fornecedores", __name__, url_prefix="/fornecedores")


def _form(form):
    return {
        "razao_social": (form.get("razao_social") or "").strip(),
        "nome_fantasia": (form.get("nome_fantasia") or "").strip(),
        "cnpj": mascara_cnpj(form.get("cnpj") or ""),
        "inscricao_estadual": (form.get("inscricao_estadual") or "").strip(),
        "telefone": (form.get("telefone") or "").strip(),
        "email": (form.get("email") or "").strip(),
        "contato_nome": (form.get("contato_nome") or "").strip(),
        "contato_fone": (form.get("contato_fone") or "").strip(),
        "cep": (form.get("cep") or "").strip(),
        "logradouro": (form.get("logradouro") or "").strip(),
        "numero": (form.get("numero") or "").strip(),
        "bairro": (form.get("bairro") or "").strip(),
        "cidade": (form.get("cidade") or "").strip(),
        "uf": (form.get("uf") or "").strip().upper()[:2],
        "site": (form.get("site") or "").strip(),
        "observacoes": (form.get("observacoes") or "").strip(),
        "ativo": 1 if form.get("ativo", "1") else 0,
    }


@bp.route("/")
@login_required("fornecedores")
def lista():
    termo = (request.args.get("q") or "").strip()
    sql = """SELECT f.*, (SELECT COUNT(*) FROM entradas e WHERE e.fornecedor_id = f.id) AS notas,
                    (SELECT COALESCE(SUM(e.total),0) FROM entradas e WHERE e.fornecedor_id = f.id) AS comprado
             FROM fornecedores f WHERE 1=1"""
    params = []
    if termo:
        sql += " AND (f.razao_social LIKE ? OR f.nome_fantasia LIKE ? OR f.cnpj LIKE ? OR f.cidade LIKE ?)"
        like = f"%{termo}%"
        params += [like] * 4
    sql += " ORDER BY f.razao_social COLLATE NOCASE"
    itens, total, page, pages = paginate(sql, tuple(params), request.args.get("page", 1, type=int), per_page=25)
    return render_template("fornecedores/lista.html", itens=itens, total=total, page=page,
                           pages=pages, termo=termo)


@bp.route("/novo", methods=["GET", "POST"])
@login_required("fornecedores")
def novo():
    if request.method == "POST":
        dados = _form(request.form)
        if not dados["razao_social"]:
            flash("Informe a razão social do fornecedor.", "erro")
            return render_template("fornecedores/form.html", fornecedor=None, dados=dados), 400
        if dados["cnpj"] and not cnpj_valido(dados["cnpj"]):
            flash("CNPJ inválido. Corrija ou deixe em branco.", "erro")
            return render_template("fornecedores/form.html", fornecedor=None, dados=dados), 400
        if dados["cnpj"]:
            dup = um("SELECT id FROM fornecedores WHERE cnpj = ?", (dados["cnpj"],))
            if dup:
                flash("Já existe um fornecedor com este CNPJ.", "erro")
                return render_template("fornecedores/form.html", fornecedor=None, dados=dados), 400
        fornecedor_id = inserir("fornecedores", dados)
        registrar_acao("criar_fornecedor", "fornecedores", fornecedor_id, dados["razao_social"])
        flash("Fornecedor cadastrado com sucesso!", "ok")
        return redirect(url_for("fornecedores.detalhe", fornecedor_id=fornecedor_id))
    return render_template("fornecedores/form.html", fornecedor=None, dados={})


@bp.route("/<int:fornecedor_id>", methods=["GET"])
@login_required("fornecedores")
def detalhe(fornecedor_id):
    fornecedor = um("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,))
    if not fornecedor:
        flash("Fornecedor não encontrado.", "erro")
        return redirect(url_for("fornecedores.lista"))
    entradas, total, page, pages = paginate(
        """SELECT e.*, u.nome AS usuario FROM entradas e LEFT JOIN usuarios u ON u.id=e.usuario_id
           WHERE e.fornecedor_id = ? ORDER BY e.id DESC""",
        (fornecedor_id,), request.args.get("page", 1, type=int), per_page=15)
    total_compras = um("SELECT COALESCE(SUM(total),0) FROM entradas WHERE fornecedor_id = ?",
                       (fornecedor_id,))[0]
    produtos = todos("""SELECT DISTINCT p.id, p.nome, p.codigo, p.principio_ativo, p.estoque, p.preco_custo
                        FROM produtos p WHERE p.id IN (SELECT produto_id FROM lotes WHERE fornecedor_id = ?)
                        ORDER BY p.nome""", (fornecedor_id,))
    return render_template("fornecedores/detalhe.html", fornecedor=fornecedor, entradas=entradas,
                           page=page, pages=pages, total_compras=total_compras, produtos=produtos)


@bp.route("/<int:fornecedor_id>/editar", methods=["GET", "POST"])
@login_required("fornecedores")
def editar(fornecedor_id):
    fornecedor = um("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,))
    if not fornecedor:
        flash("Fornecedor não encontrado.", "erro")
        return redirect(url_for("fornecedores.lista"))
    if request.method == "POST":
        dados = _form(request.form)
        if not dados["razao_social"]:
            flash("A razão social não pode ficar vazia.", "erro")
            return render_template("fornecedores/form.html", fornecedor=fornecedor, dados=dados), 400
        if dados["cnpj"] and not cnpj_valido(dados["cnpj"]):
            flash("CNPJ inválido. Corrija ou deixe em branco.", "erro")
            return render_template("fornecedores/form.html", fornecedor=fornecedor, dados=dados), 400
        dup = um("SELECT id FROM fornecedores WHERE cnpj = ? AND id != ?", (dados["cnpj"], fornecedor_id))
        if dados["cnpj"] and dup:
            flash("Outro fornecedor já usa este CNPJ.", "erro")
            return render_template("fornecedores/form.html", fornecedor=fornecedor, dados=dados), 400
        dados["atualizado_em"] = agora()
        atualizar("fornecedores", fornecedor_id, dados)
        registrar_acao("editar_fornecedor", "fornecedores", fornecedor_id, dados["razao_social"])
        flash("Fornecedor atualizado!", "ok")
        return redirect(url_for("fornecedores.detalhe", fornecedor_id=fornecedor_id))
    return render_template("fornecedores/form.html", fornecedor=fornecedor, dados=fornecedor)


@bp.route("/<int:fornecedor_id>/excluir", methods=["POST"])
@login_required("fornecedores")
def excluir(fornecedor_id):
    fornecedor = um("SELECT * FROM fornecedores WHERE id = ?", (fornecedor_id,))
    if not fornecedor:
        flash("Fornecedor não encontrado.", "erro")
        return redirect(url_for("fornecedores.lista"))
    db = get_db()
    db.execute("UPDATE fornecedores SET ativo = 0 WHERE id = ?", (fornecedor_id,))
    db.commit()
    registrar_acao("desativar_fornecedor", "fornecedores", fornecedor_id, fornecedor["razao_social"])
    flash("Fornecedor desativado.", "ok")
    return redirect(url_for("fornecedores.lista"))


@bp.route("/api/buscar")
@login_required("fornecedores")
def api_buscar():
    termo = (request.args.get("q") or "").strip()
    if len(termo) < 2:
        return jsonify({"fornecedores": []})
    like = f"%{termo}%"
    itens = todos("""SELECT id, razao_social, nome_fantasia, cnpj, cidade, uf FROM fornecedores
                     WHERE ativo=1 AND (razao_social LIKE ? OR nome_fantasia LIKE ? OR cnpj LIKE ?)
                     ORDER BY razao_social LIMIT 15""", (like, like, like))
    return jsonify({"fornecedores": [dict(i) for i in itens]})
