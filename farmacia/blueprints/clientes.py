"""Cadastro de clientes, histórico de compras e ficha (conta corrente)."""
from flask import (Blueprint, flash, g, jsonify, redirect, render_template, request,
                   url_for)

from ..db import agora, atualizar, get_db, inserir, paginate, todos, um
from ..security import login_required, registrar_acao
from ..services import ErroNegocio, pagar_ficha
from ..utils import (brl, cpf_valido, data_br, data_iso, dias_ate, idade,
                     mascara_cpf)

bp = Blueprint("clientes", __name__, url_prefix="/clientes")


def _form(form):
    return {
        "nome": (form.get("nome") or "").strip(),
        "cpf": mascara_cpf(form.get("cpf") or ""),
        "rg": (form.get("rg") or "").strip(),
        "data_nascimento": data_iso(form.get("data_nascimento")),
        "telefone": (form.get("telefone") or "").strip(),
        "celular": (form.get("celular") or "").strip(),
        "email": (form.get("email") or "").strip(),
        "cep": (form.get("cep") or "").strip(),
        "logradouro": (form.get("logradouro") or "").strip(),
        "numero": (form.get("numero") or "").strip(),
        "complemento": (form.get("complemento") or "").strip(),
        "bairro": (form.get("bairro") or "").strip(),
        "cidade": (form.get("cidade") or "").strip(),
        "uf": (form.get("uf") or "").strip().upper()[:2],
        "observacoes": (form.get("observacoes") or "").strip(),
        "limite_credito": _numero(form.get("limite_credito")),
        "ativo": 1 if form.get("ativo", "1") else 0,
    }


def _numero(texto):
    if texto is None:
        return 0.0
    texto = str(texto).strip().replace("R$", "").strip()
    if not texto:
        return 0.0
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


@bp.route("/")
@login_required("clientes")
def lista():
    termo = (request.args.get("q") or "").strip()
    situacao = request.args.get("situacao") or ""
    sql = "SELECT * FROM clientes WHERE 1=1"
    params = []
    if termo:
        sql += " AND (nome LIKE ? OR cpf LIKE ? OR celular LIKE ? OR telefone LIKE ? OR email LIKE ?)"
        like = f"%{termo}%"
        params += [like] * 5
    if situacao == "debito":
        sql += " AND saldo_credito > 0"
    elif situacao == "ativo":
        sql += " AND ativo = 1"
    elif situacao == "inativo":
        sql += " AND ativo = 0"
    sql += " ORDER BY nome COLLATE NOCASE"
    page = request.args.get("page", 1, type=int)
    itens, total, page, pages = paginate(sql, tuple(params), page, per_page=25)
    return render_template("clientes/lista.html", itens=itens, total=total, page=page,
                           pages=pages, termo=termo, situacao=situacao)


@bp.route("/novo", methods=["GET", "POST"])
@login_required("clientes")
def novo():
    if request.method == "POST":
        dados = _form(request.form)
        if not dados["nome"]:
            flash("Informe o nome do cliente.", "erro")
            return render_template("clientes/form.html", cliente=None, dados=dados), 400
        if dados["cpf"]:
            if not cpf_valido(dados["cpf"]):
                flash("CPF inválido. Corrija ou deixe em branco.", "erro")
                return render_template("clientes/form.html", cliente=None, dados=dados), 400
            dup = um("SELECT id FROM clientes WHERE cpf = ?", (dados["cpf"],))
            if dup:
                flash("Já existe um cliente cadastrado com este CPF.", "erro")
                return render_template("clientes/form.html", cliente=None, dados=dados), 400
        cliente_id = inserir("clientes", dados)
        registrar_acao("criar_cliente", "clientes", cliente_id, f"Cadastro de {dados['nome']}")
        flash(f"Cliente '{dados['nome']}' cadastrado!", "ok")
        return redirect(url_for("clientes.detalhe", cliente_id=cliente_id))
    return render_template("clientes/form.html", cliente=None, dados={})


@bp.route("/<int:cliente_id>", methods=["GET"])
@login_required("clientes")
def detalhe(cliente_id):
    cliente = um("SELECT * FROM clientes WHERE id = ?", (cliente_id,))
    if cliente is None:
        flash("Cliente não encontrado.", "erro")
        return redirect(url_for("clientes.lista"))
    compras, total_compras, page, pages = paginate(
        """SELECT v.*, (SELECT COUNT(*) FROM venda_itens vi WHERE vi.venda_id = v.id) AS itens
           FROM vendas v WHERE v.cliente_id = ? ORDER BY v.id DESC""",
        (cliente_id,), request.args.get("page", 1, type=int), per_page=15)
    ficha = todos("SELECT * FROM fichas WHERE cliente_id = ? ORDER BY id DESC LIMIT 60", (cliente_id,))
    total_comprado = um("""SELECT COALESCE(SUM(total),0) FROM vendas
                           WHERE cliente_id = ? AND status='concluida'""", (cliente_id,))[0]
    ultima = um("""SELECT data, total FROM vendas WHERE cliente_id=? AND status='concluida'
                   ORDER BY id DESC LIMIT 1""", (cliente_id,))
    em_aberto = [l for l in ficha if l["tipo"] == "lancamento"]
    return render_template(
        "clientes/detalhe.html", cliente=cliente, compras=compras, ficha=ficha,
        page=page, pages=pages, total_compras=total_compras, total_comprado=total_comprado,
        ultima=ultima, em_aberto=em_aberto,
    )


@bp.route("/<int:cliente_id>/editar", methods=["GET", "POST"])
@login_required("clientes")
def editar(cliente_id):
    cliente = um("SELECT * FROM clientes WHERE id = ?", (cliente_id,))
    if cliente is None:
        flash("Cliente não encontrado.", "erro")
        return redirect(url_for("clientes.lista"))
    if request.method == "POST":
        dados = _form(request.form)
        if not dados["nome"]:
            flash("O nome não pode ficar vazio.", "erro")
            return render_template("clientes/form.html", cliente=cliente, dados=dados), 400
        if dados["cpf"] and not cpf_valido(dados["cpf"]):
            flash("CPF inválido. Corrija ou deixe em branco.", "erro")
            return render_template("clientes/form.html", cliente=cliente, dados=dados), 400
        dup = um("SELECT id FROM clientes WHERE cpf = ? AND id != ?", (dados["cpf"], cliente_id))
        if dados["cpf"] and dup:
            flash("Outro cliente já usa este CPF.", "erro")
            return render_template("clientes/form.html", cliente=cliente, dados=dados), 400
        dados["atualizado_em"] = agora()
        atualizar("clientes", cliente_id, dados)
        registrar_acao("editar_cliente", "clientes", cliente_id, f"Atualização de {dados['nome']}")
        flash("Cliente atualizado!", "ok")
        return redirect(url_for("clientes.detalhe", cliente_id=cliente_id))
    return render_template("clientes/form.html", cliente=cliente, dados=cliente)


@bp.route("/<int:cliente_id>/excluir", methods=["POST"])
@login_required("clientes")
def excluir(cliente_id):
    cliente = um("SELECT * FROM clientes WHERE id = ?", (cliente_id,))
    if not cliente:
        flash("Cliente não encontrado.", "erro")
        return redirect(url_for("clientes.lista"))
    tem_compras = um("SELECT 1 FROM vendas WHERE cliente_id = ? LIMIT 1", (cliente_id,))
    db = get_db()
    if tem_compras:
        db.execute("UPDATE clientes SET ativo = 0, atualizado_em = ? WHERE id = ?", (agora(), cliente_id))
        flash("Cliente possui histórico de compras: ele foi apenas desativado.", "ok")
    else:
        db.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))
        flash("Cliente excluído.", "ok")
    db.commit()
    registrar_acao("excluir_cliente", "clientes", cliente_id, f"Remoção de {cliente['nome']}")
    return redirect(url_for("clientes.lista"))


@bp.route("/<int:cliente_id>/pagamento", methods=["POST"])
@login_required("clientes")
def pagamento(cliente_id):
    try:
        valor = _numero(request.form.get("valor"))
        forma = request.form.get("forma") or "dinheiro"
        descricao = (request.form.get("descricao") or "Pagamento de ficha").strip()
        saldo = pagar_ficha(cliente_id, valor, g.get("usuario"), descricao, forma)
        flash(f"Pagamento de {brl(valor)} registrado. Novo saldo: {brl(saldo)}.", "ok")
    except (ErroNegocio, ValueError, TypeError) as erro:
        flash(str(erro), "erro")
    return redirect(url_for("clientes.detalhe", cliente_id=cliente_id))


@bp.route("/api/buscar")
@login_required("clientes")
def api_buscar():
    termo = (request.args.get("q") or "").strip()
    if len(termo) < 1:
        return jsonify({"clientes": []})
    like = f"%{termo}%"
    itens = todos("""SELECT id, nome, cpf, celular, telefone, saldo_credito, limite_credito, pontos
                     FROM clientes WHERE ativo=1 AND (nome LIKE ? OR cpf LIKE ? OR celular LIKE ?)
                     ORDER BY nome COLLATE NOCASE LIMIT 20""", (like, like, like))
    return jsonify({"clientes": [dict(i) for i in itens]})


@bp.route("/api/<int:cliente_id>/extrato")
@login_required("clientes")
def api_extrato(cliente_id):
    cliente = um("SELECT id, nome, cpf, saldo_credito, limite_credito FROM clientes WHERE id = ?", (cliente_id,))
    if not cliente:
        return jsonify({"erro": "Cliente não encontrado."}), 404
    lancamentos = todos("SELECT * FROM fichas WHERE cliente_id = ? ORDER BY id DESC LIMIT 100", (cliente_id,))
    return jsonify({"cliente": dict(cliente), "lancamentos": [dict(l) for l in lancamentos]})
