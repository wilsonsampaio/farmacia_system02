"""Cadastro de medicamentos: ficha completa, fotos, bula, preços e estoque."""
import os

from flask import (Blueprint, flash, g, jsonify, redirect, render_template,
                   request, url_for)

from ..db import agora, atualizar, executar, get_db, inserir, paginate, todos, um
from ..security import login_required, registrar_acao
from ..services import ErroNegocio, ajustar_estoque, movimentacoes_recentes, status_estoque
from ..utils import (CLASSES_TERAPEUTICAS, TARJAS, apagar_foto, brl, caminho_foto,
                     data_br, foto_principal, salvar_foto, digitos)
from ..views import media_url

bp = Blueprint("produtos", __name__, url_prefix="/produtos")


def _dados_formulario(form, dados=None):
    dados = dados or {}
    return {
        "codigo": (form.get("codigo") or "").strip(),
        "ean": digitos(form.get("ean")),
        "nome": (form.get("nome") or "").strip(),
        "principio_ativo": (form.get("principio_ativo") or "").strip(),
        "laboratorio": (form.get("laboratorio") or "").strip(),
        "classe_terapeutica": (form.get("classe_terapeutica") or "").strip(),
        "apresentacao": (form.get("apresentacao") or "").strip(),
        "concentracao": (form.get("concentracao") or "").strip(),
        "tarja": form.get("tarja") or "livre",
        "controlado": 1 if form.get("controlado") else 0,
        "receita_obrigatoria": 1 if form.get("receita_obrigatoria") else 0,
        "registro_anvisa": (form.get("registro_anvisa") or "").strip(),
        "ncm": (form.get("ncm") or "").strip(),
        "unidade": (form.get("unidade") or "UN").strip().upper(),
        "preco_custo": _numero(form.get("preco_custo")),
        "preco_venda": _numero(form.get("preco_venda")),
        "estoque_minimo": int(_numero(form.get("estoque_minimo"))),
        "localizacao": (form.get("localizacao") or "").strip(),
        "ativo": 1 if form.get("ativo", "1") else 0,
        "observacoes": (form.get("observacoes") or "").strip(),
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


DADOS_BULA = ("indicacoes", "posologia", "contraindicacoes", "efeitos_adversos", "advertencias",
              "interacoes", "gravidez", "sobredoagem", "armazenamento", "excipientes", "link_bula")


def _salvar_bula(produto_id, form):
    dados = {campo: (form.get(f"bula_{campo}") or "").strip() for campo in DADOS_BULA}
    existente = um("SELECT 1 FROM bulas WHERE produto_id = ?", (produto_id,))
    dados["atualizada_em"] = agora()
    if existente:
        atualizar("bulas", produto_id, dados)
    else:
        dados["produto_id"] = produto_id
        inserir("bulas", dados)


@bp.route("/")
@login_required("produtos.consultar")
def lista():
    termo = (request.args.get("q") or "").strip()
    classe = request.args.get("classe") or ""
    laboratorio = request.args.get("lab") or ""
    tarja = request.args.get("tarja") or ""
    situacao = request.args.get("situacao") or ""
    ordenar = request.args.get("ord") or "nome"

    sql = """SELECT p.*, (SELECT arquivo FROM produto_fotos f WHERE f.produto_id = p.id
                          ORDER BY principal DESC, id LIMIT 1) AS foto
             FROM produtos p WHERE 1=1"""
    params = []
    if termo:
        sql += """ AND (p.nome LIKE ? OR p.principio_ativo LIKE ? OR p.codigo LIKE ? OR p.ean LIKE ?
                     OR p.laboratorio LIKE ?)"""
        like = f"%{termo}%"
        params += [like] * 5
    if classe:
        sql += " AND p.classe_terapeutica = ?"
        params.append(classe)
    if laboratorio:
        sql += " AND p.laboratorio = ?"
        params.append(laboratorio)
    if tarja:
        sql += " AND p.tarja = ?"
        params.append(tarja)
    if situacao == "baixo":
        sql += " AND p.estoque <= p.estoque_minimo"
    elif situacao == "zerado":
        sql += " AND p.estoque <= 0"
    elif situacao == "inativo":
        sql += " AND p.ativo = 0"
    elif situacao == "ativo":
        sql += " AND p.ativo = 1"

    colunas = {"nome": "p.nome", "estoque": "p.estoque", "preco": "p.preco_venda",
               "laboratorio": "p.laboratorio", "classe": "p.classe_terapeutica"}
    sql += f" ORDER BY {colunas.get(ordenar, 'p.nome')} COLLATE NOCASE"

    page = request.args.get("page", 1, type=int)
    itens, total, page, pages = paginate(sql, tuple(params), page, per_page=24)

    laboratorios = todos("SELECT DISTINCT laboratorio FROM produtos WHERE laboratorio IS NOT NULL AND laboratorio != '' ORDER BY 1")
    classes = todos("SELECT DISTINCT classe_terapeutica FROM produtos WHERE classe_terapeutica IS NOT NULL AND classe_terapeutica != '' ORDER BY 1")

    return render_template(
        "produtos/lista.html",
        itens=itens, total=total, page=page, pages=pages,
        termo=termo, classe=classe, laboratorio=laboratorio, tarja=tarja,
        situacao=situacao, ordenar=ordenar,
        laboratorios=laboratorios, classes=classes, tarjas=TARJAS,
        classes_cad=CLASSES_TERAPEUTICAS,
    )


@bp.route("/novo", methods=["GET", "POST"])
@login_required("produtos")
def novo():
    if request.method == "POST":
        dados = _dados_formulario(request.form)
        if not dados["nome"]:
            flash("Informe o nome do medicamento.", "erro")
            return render_template("produtos/form.html", produto=None, dados=dados,
                                   tarjas=TARJAS, classes=CLASSES_TERAPEUTICAS), 400
        if not dados["codigo"]:
            dados["codigo"] = f"PROD{os.urandom(3).hex().upper()}"
        existente = um("SELECT id FROM produtos WHERE codigo = ? COLLATE NOCASE", (dados["codigo"],))
        if existente:
            flash(f"Já existe um produto com o código '{dados['codigo']}'.", "erro")
            return render_template("produtos/form.html", produto=None, dados=dados,
                                   tarjas=TARJAS, classes=CLASSES_TERAPEUTICAS), 400
        produto_id = inserir("produtos", dados)
        _salvar_bula(produto_id, request.form)

        arquivo = salvar_foto(request.files.get("foto"))
        if arquivo:
            inserir("produto_fotos", {"produto_id": produto_id, "arquivo": arquivo, "principal": 1})
        # estoque inicial via lote (se informado)
        estoque_inicial = int(_numero(request.form.get("estoque_inicial")))
        if estoque_inicial > 0:
            from ..services import entrada_estoque
            entrada_estoque(produto_id, estoque_inicial,
                            lote=request.form.get("lote_inicial") or "INICIAL",
                            validade=request.form.get("validade_inicial"),
                            custo=dados["preco_custo"], observacao="Estoque inicial do cadastro")

        registrar_acao("criar_produto", "produtos", produto_id, f"Cadastro de {dados['nome']}")
        flash(f"Medicamento '{dados['nome']}' cadastrado com sucesso!", "ok")
        return redirect(url_for("produtos.detalhe", produto_id=produto_id))

    return render_template("produtos/form.html", produto=None, dados={}, tarjas=TARJAS,
                           classes=CLASSES_TERAPEUTICAS)


@bp.route("/<int:produto_id>/editar", methods=["GET", "POST"])
@login_required("produtos")
def editar(produto_id):
    produto = um("SELECT * FROM produtos WHERE id = ?", (produto_id,))
    if produto is None:
        flash("Medicamento não encontrado.", "erro")
        return redirect(url_for("produtos.lista"))
    bula = um("SELECT * FROM bulas WHERE produto_id = ?", (produto_id,))

    if request.method == "POST":
        dados = _dados_formulario(request.form, produto)
        if not dados["nome"]:
            flash("O nome do medicamento não pode ficar vazio.", "erro")
            return render_template("produtos/form.html", produto=produto, bula=bula, dados=dados,
                                   tarjas=TARJAS, classes=CLASSES_TERAPEUTICAS), 400
        duplicado = um("SELECT id FROM produtos WHERE codigo = ? COLLATE NOCASE AND id != ?",
                       (dados["codigo"], produto_id))
        if duplicado:
            flash(f"O código '{dados['codigo']}' já está sendo usado por outro produto.", "erro")
            return render_template("produtos/form.html", produto=produto, bula=bula, dados=dados,
                                   tarjas=TARJAS, classes=CLASSES_TERAPEUTICAS), 400
        dados["atualizado_em"] = agora()
        atualizar("produtos", produto_id, dados)
        _salvar_bula(produto_id, request.form)
        arquivo = salvar_foto(request.files.get("foto"))
        if arquivo:
            principal = 0 if um("SELECT 1 FROM produto_fotos WHERE produto_id = ?", (produto_id,)) else 1
            inserir("produto_fotos", {"produto_id": produto_id, "arquivo": arquivo, "principal": principal})
        registrar_acao("editar_produto", "produtos", produto_id, f"Atualização de {dados['nome']}")
        flash("Medicamento atualizado com sucesso!", "ok")
        return redirect(url_for("produtos.detalhe", produto_id=produto_id))

    return render_template("produtos/form.html", produto=produto, bula=bula,
                           dados=produto, tarjas=TARJAS, classes=CLASSES_TERAPEUTICAS)


@bp.route("/<int:produto_id>")
@login_required("produtos.consultar")
def detalhe(produto_id):
    produto = um("SELECT * FROM produtos WHERE id = ?", (produto_id,))
    if produto is None:
        flash("Medicamento não encontrado.", "erro")
        return redirect(url_for("produtos.lista"))
    bula = um("SELECT * FROM bulas WHERE produto_id = ?", (produto_id,))
    db_fotos = todos("SELECT * FROM produto_fotos WHERE produto_id = ? ORDER BY principal DESC, ordem, id",
                     (produto_id,))
    lotes = todos("""SELECT l.*, f.razao_social FROM lotes l
                     LEFT JOIN fornecedores f ON f.id = l.fornecedor_id
                     WHERE l.produto_id = ? AND l.quantidade > 0
                     ORDER BY (l.validade IS NULL OR l.validade=''), l.validade""",
                  (produto_id,))
    movimentos = movimentacoes_recentes(produto_id, 30)
    vendas = todos(
        """SELECT v.id, v.numero, v.data, vi.quantidade, vi.preco_unitario, vi.subtotal, c.nome AS cliente
           FROM venda_itens vi JOIN vendas v ON v.id = vi.venda_id
           LEFT JOIN clientes c ON c.id = v.cliente_id
           WHERE vi.produto_id = ? AND v.status='concluida'
           ORDER BY v.id DESC LIMIT 25""", (produto_id,))
    total_vendido = um("""SELECT COALESCE(SUM(vi.quantidade),0) qtd, COALESCE(SUM(vi.subtotal),0) valor
                          FROM venda_itens vi JOIN vendas v ON v.id=vi.venda_id
                          WHERE vi.produto_id = ? AND v.status='concluida'""", (produto_id,))
    fichas = todos("""SELECT v.numero, v.data, vi.quantidade, vi.subtotal FROM venda_itens vi
                      JOIN vendas v ON v.id=vi.venda_id WHERE vi.produto_id=?
                      ORDER BY v.id DESC""", (produto_id,))
    situacao = status_estoque(produto["estoque"], produto["estoque_minimo"])

    return render_template(
        "produtos/detalhe.html",
        produto=produto, bula=bula, fotos=db_fotos, lotes=lotes, movimentos=movimentos,
        vendas=vendas, situacao=situacao, total_vendido=total_vendido,
        tarjas=TARJAS, classes=CLASSES_TERAPEUTICAS, digitos=digitos,
        foto_principal=foto_principal(produto_id),
    )


@bp.route("/<int:produto_id>/excluir", methods=["POST"])
@login_required("produtos")
def excluir(produto_id):
    produto = um("SELECT * FROM produtos WHERE id = ?", (produto_id,))
    if produto is None:
        flash("Medicamento não encontrado.", "erro")
        return redirect(url_for("produtos.lista"))
    if request.form.get("confirmar") != produto["nome"]:
        flash("Digite exatamente o nome do medicamento para confirmar a exclusão.", "erro")
        return redirect(url_for("produtos.detalhe", produto_id=produto_id))
    db = get_db()
    db.execute("UPDATE produtos SET ativo = 0, atualizado_em = datetime('now','localtime') WHERE id = ?",
               (produto_id,))
    db.commit()
    registrar_acao("desativar_produto", "produtos", produto_id, f"Desativação de {produto['nome']}")
    flash(f"'{produto['nome']}' foi desativado (o histórico de vendas foi preservado).", "ok")
    return redirect(url_for("produtos.lista"))


@bp.route("/<int:produto_id>/reativar", methods=["POST"])
@login_required("produtos")
def reativar(produto_id):
    db = get_db()
    db.execute("UPDATE produtos SET ativo = 1, atualizado_em = datetime('now','localtime') WHERE id = ?", (produto_id,))
    db.commit()
    registrar_acao("reativar_produto", "produtos", produto_id, "Reativação de produto")
    flash("Medicamento reativado.", "ok")
    return redirect(url_for("produtos.detalhe", produto_id=produto_id))


@bp.route("/<int:produto_id>/foto", methods=["POST"])
@login_required("produtos")
def enviar_foto(produto_id):
    if not um("SELECT 1 FROM produtos WHERE id = ?", (produto_id,)):
        return jsonify({"erro": "Produto não encontrado."}), 404
    arquivo = salvar_foto(request.files.get("foto"))
    if not arquivo:
        return jsonify({"erro": "Envie uma imagem válida (JPG, PNG ou WEBP, até 8 MB)."}), 400
    principal = 0 if um("SELECT 1 FROM produto_fotos WHERE produto_id = ?", (produto_id,)) else 1
    foto_id = inserir("produto_fotos", {"produto_id": produto_id, "arquivo": arquivo, "principal": principal})
    registrar_acao("foto_produto", "produto_fotos", foto_id, "Nova foto enviada")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "arquivo": arquivo, "url": media_url(arquivo)})
    flash("Foto enviada com sucesso!", "ok")
    return redirect(url_for("produtos.detalhe", produto_id=produto_id))


@bp.route("/<int:produto_id>/foto/<int:foto_id>/excluir", methods=["POST"])
@login_required("produtos")
def excluir_foto(produto_id, foto_id):
    foto = um("SELECT * FROM produto_fotos WHERE id = ? AND produto_id = ?", (foto_id, produto_id))
    if foto:
        apagar_foto(foto["arquivo"])
        db = get_db()
        db.execute("DELETE FROM produto_fotos WHERE id = ?", (foto_id,))
        if foto["principal"]:
            restante = um("SELECT id FROM produto_fotos WHERE produto_id = ? ORDER BY id LIMIT 1", (produto_id,))
            if restante:
                db.execute("UPDATE produto_fotos SET principal = 1 WHERE id = ?", (restante["id"],))
        db.commit()
        flash("Foto removida.", "ok")
    return redirect(request.referrer or url_for("produtos.detalhe", produto_id=produto_id))


@bp.route("/<int:produto_id>/foto/<int:foto_id>/principal", methods=["POST"])
@login_required("produtos")
def foto_principal_acao(produto_id, foto_id):
    db = get_db()
    db.execute("UPDATE produto_fotos SET principal = 0 WHERE produto_id = ?", (produto_id,))
    db.execute("UPDATE produto_fotos SET principal = 1 WHERE id = ? AND produto_id = ?", (foto_id, produto_id))
    db.commit()
    return redirect(request.referrer or url_for("produtos.detalhe", produto_id=produto_id))


@bp.route("/<int:produto_id>/ajuste", methods=["POST"])
@login_required("estoque")
def ajuste(produto_id):
    produto = um("SELECT * FROM produtos WHERE id = ?", (produto_id,))
    if produto is None:
        flash("Produto não encontrado.", "erro")
        return redirect(url_for("produtos.lista"))
    try:
        novo = int(_numero(request.form.get("novo_saldo")))
        delta = ajustar_estoque(produto_id, novo, motivo=request.form.get("motivo") or "Ajuste manual",
                                usuario_id=(g.get("usuario") or {}).get("id"))
        registrar_acao("ajuste_estoque", "produtos", produto_id,
                       f"{produto['nome']}: {produto['estoque']} -> {novo}")
        flash(f"Estoque ajustado de {produto['estoque']} para {novo} ({'+' if delta >= 0 else ''}{delta}).", "ok")
    except (ErroNegocio, ValueError) as erro:
        flash(str(erro), "erro")
    return redirect(request.referrer or url_for("produtos.detalhe", produto_id=produto_id))


@bp.route("/api/buscar")
@login_required("produtos")
def api_buscar():
    """Busca rápida usada no PDV (nome, código, EAN, princípio ativo)."""
    termo = (request.args.get("q") or "").strip()
    if len(termo) < 1:
        return jsonify({"produtos": []})
    like = f"%{termo}%"
    itens = todos(
        """SELECT p.id, p.codigo, p.ean, p.nome, p.principio_ativo, p.laboratorio, p.apresentacao,
                  p.concentracao, p.tarja, p.controlado, p.preco_venda, p.estoque, p.unidade,
                  p.classe_terapeutica,
                  (SELECT arquivo FROM produto_fotos f WHERE f.produto_id = p.id
                   ORDER BY principal DESC, id LIMIT 1) AS foto
           FROM produtos p
           WHERE p.ativo = 1 AND (p.nome LIKE ? OR p.codigo LIKE ? OR p.ean LIKE ?
                                  OR p.principio_ativo LIKE ? OR p.laboratorio LIKE ?)
           ORDER BY CASE WHEN p.codigo = ? OR p.ean = ? THEN 0 ELSE 1 END, p.nome COLLATE NOCASE
           LIMIT 30""",
        (like, like, like, like, like, termo, termo))
    return jsonify({"produtos": [dict(i) for i in itens]})


@bp.route("/api/<int:produto_id>")
@login_required("produtos")
def api_detalhe(produto_id):
    produto = um("""SELECT p.*, (SELECT arquivo FROM produto_fotos f WHERE f.produto_id=p.id
                    ORDER BY principal DESC, id LIMIT 1) AS foto FROM produtos p WHERE p.id = ?""",
                 (produto_id,))
    if produto is None:
        return jsonify({"erro": "Produto não encontrado."}), 404
    return jsonify(dict(produto))
