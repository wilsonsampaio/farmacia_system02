"""Controle de estoque: entradas de nota, lotes, validades, perdas e movimentações."""
from datetime import datetime

from flask import (Blueprint, flash, g, jsonify, redirect, render_template, request,
                   url_for)

from ..db import get_db, paginate, todos, um
from ..security import login_required, registrar_acao
from ..services import (ErroNegocio, ajustar_estoque, baixar_estoque,
                        devolver_estoque, registrar_entrada_nota, status_estoque)
from ..utils import brl, dias_ate, valor_de

bp = Blueprint("estoque", __name__, url_prefix="/estoque")


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
@login_required("estoque")
def index():
    db = get_db()
    aba = request.args.get("aba") or "resumo"
    alerta_dias = int((um("SELECT valor FROM parametros WHERE chave='estoque_alerta_dias'") or {"valor": 60})["valor"] or 60)

    resumo = {
        "itens": db.execute("SELECT COUNT(*) FROM produtos WHERE ativo=1").fetchone()[0],
        "unidades": db.execute("SELECT COALESCE(SUM(estoque),0) FROM produtos WHERE ativo=1").fetchone()[0],
        "custo": db.execute("SELECT COALESCE(SUM(estoque * preco_custo),0) FROM produtos WHERE ativo=1").fetchone()[0],
        "venda": db.execute("SELECT COALESCE(SUM(estoque * preco_venda),0) FROM produtos WHERE ativo=1").fetchone()[0],
        "baixos": db.execute("SELECT COUNT(*) FROM produtos WHERE ativo=1 AND estoque <= estoque_minimo AND estoque > 0").fetchone()[0],
        "zerados": db.execute("SELECT COUNT(*) FROM produtos WHERE ativo=1 AND estoque <= 0").fetchone()[0],
        "vencidos": db.execute("""SELECT COALESCE(SUM(l.quantidade),0) FROM lotes l
                                  WHERE l.quantidade>0 AND l.validade IS NOT NULL AND date(l.validade) < date('now')""").fetchone()[0],
        "vencendo": db.execute("""SELECT COALESCE(SUM(l.quantidade),0) FROM lotes l
                                  WHERE l.quantidade>0 AND l.validade IS NOT NULL
                                    AND date(l.validade) BETWEEN date('now') AND date('now', ?)""",
                               (f"+{alerta_dias} days",)).fetchone()[0],
    }

    baixos = todos("""SELECT id, nome, codigo, estoque, estoque_minimo, principio_ativo, laboratorio, unidade,
                             CASE WHEN estoque <= 0 THEN 'zerado' ELSE 'baixo' END AS tipo
                      FROM produtos WHERE ativo=1 AND estoque <= estoque_minimo
                      ORDER BY (estoque - estoque_minimo), nome""")

    vencimentos = [dict(l) for l in todos(
        """SELECT l.id, l.produto_id, p.nome, p.codigo, l.lote, l.validade, l.quantidade, l.fornecedor_id,
                  f.razao_social, l.preco_custo,
                  CAST(julianday(l.validade) - julianday('now') AS INTEGER) AS dias
           FROM lotes l JOIN produtos p ON p.id = l.produto_id
           LEFT JOIN fornecedores f ON f.id = l.fornecedor_id
           WHERE l.quantidade > 0 AND l.validade IS NOT NULL AND l.validade != ''
             AND date(l.validade) <= date('now', ?)
           ORDER BY date(l.validade)""", (f"+{alerta_dias} days",))]
    for linha in vencimentos:
        linha_dias = dias_ate(linha["validade"])
        linha["situacao"] = "vencido" if linha_dias is not None and linha_dias < 0 else (
            "critico" if linha_dias is not None and linha_dias <= 15 else "atencao")

    # movimentações
    page_mov = request.args.get("page", 1, type=int)
    filtros_mov = ["1=1"]
    params_mov = []
    if request.args.get("produto"):
        filtros_mov.append("p.nome LIKE ?")
        params_mov.append(f"%{request.args.get('produto')}%")
    if request.args.get("tipo"):
        filtros_mov.append("m.tipo = ?")
        params_mov.append(request.args.get("tipo"))
    if request.args.get("de"):
        filtros_mov.append("date(m.criado_em) >= date(?)")
        params_mov.append(request.args.get("de"))
    if request.args.get("ate"):
        filtros_mov.append("date(m.criado_em) <= date(?)")
        params_mov.append(request.args.get("ate"))
    sql_mov = f"""SELECT m.*, p.nome AS produto, p.codigo, u.nome AS usuario
                  FROM movimentacoes m JOIN produtos p ON p.id = m.produto_id
                  LEFT JOIN usuarios u ON u.id = m.usuario_id
                  WHERE {' AND '.join(filtros_mov)} ORDER BY m.id DESC"""
    movs, total_mov, page_mov, pages_mov = paginate(sql_mov, tuple(params_mov), page_mov, per_page=30)

    # entradas (notas)
    entradas = todos("""SELECT e.*, f.razao_social, u.nome AS usuario,
                               (SELECT COUNT(*) FROM movimentacoes m WHERE m.tipo_ref='entrada' AND m.ref_id=e.id) AS itens
                        FROM entradas e LEFT JOIN fornecedores f ON f.id=e.fornecedor_id
                        LEFT JOIN usuarios u ON u.id=e.usuario_id
                        ORDER BY e.id DESC LIMIT 60""")

    # lotes
    lotes = todos("""SELECT l.*, p.nome AS produto, p.codigo, f.razao_social,
                            CAST(julianday(l.validade) - julianday('now') AS INTEGER) AS dias
                     FROM lotes l JOIN produtos p ON p.id=l.produto_id
                     LEFT JOIN fornecedores f ON f.id=l.fornecedor_id
                     WHERE l.quantidade > 0
                     ORDER BY (l.validade IS NULL OR l.validade=''), l.validade, p.nome""")

    # inventário (impressão)
    inventario = todos("""SELECT p.codigo, p.nome, p.principio_ativo, p.laboratorio, p.estoque,
                                 p.estoque_minimo, p.preco_custo, p.preco_venda, p.localizacao, p.unidade
                          FROM produtos p WHERE p.ativo=1 ORDER BY p.nome COLLATE NOCASE""")

    return render_template(
        "estoque/index.html",
        aba=aba, resumo=resumo, baixos=baixos, vencimentos=vencimentos,
        movs=movs, page=page_mov, pages=pages_mov, total_mov=total_mov,
        entradas=entradas, lotes=lotes, inventario=inventario, alerta_dias=alerta_dias,
    )


@bp.route("/entrada", methods=["GET", "POST"])
@login_required("estoque")
def entrada():
    fornecedores = todos("SELECT id, razao_social, nome_fantasia FROM fornecedores WHERE ativo=1 ORDER BY razao_social")
    if request.method == "POST":
        fornecedor_id = request.form.get("fornecedor_id") or None
        numero = (request.form.get("numero") or "").strip() or None
        data_emissao = request.form.get("data_emissao") or None
        observacao = (request.form.get("observacao") or "").strip()
        produtos = request.form.getlist("produto_id")
        quantidades = request.form.getlist("quantidade")
        lotes = request.form.getlist("lote")
        validades = request.form.getlist("validade")
        custos = request.form.getlist("preco_unitario")

        itens = []
        for i, pid in enumerate(produtos):
            if not pid:
                continue
            qtd = int(_numero(quantidades[i]) if i < len(quantidades) else 0)
            if qtd <= 0:
                continue
            itens.append({
                "produto_id": int(pid),
                "quantidade": qtd,
                "lote": (lotes[i] or "").strip() if i < len(lotes) else None,
                "validade": (validades[i] or "").strip() if i < len(validades) else None,
                "preco_unitario": _numero(custos[i]) if i < len(custos) else 0,
            })
        try:
            entrada_id, total = registrar_entrada_nota(
                fornecedor_id=int(fornecedor_id) if fornecedor_id else None,
                itens=itens, usuario_id=valor_de(g.get("usuario"), "id"),
                numero=numero, data_emissao=data_emissao, observacao=observacao)
            flash(f"Entrada registrada com sucesso! {len(itens)} item(ns) - total {brl(total)}.", "ok")
            return redirect(url_for("estoque.index", aba="entradas"))
        except (ErroNegocio, ValueError) as erro:
            flash(str(erro), "erro")
        except Exception:
            get_db().rollback()
            flash("Erro inesperado ao registrar a entrada. Verifique os dados informados.", "erro")
    return render_template("estoque/entrada_form.html", fornecedores=fornecedores)


@bp.route("/entrada/<int:entrada_id>")
@login_required("estoque")
def entrada_detalhe(entrada_id):
    entrada_row = um("""SELECT e.*, f.razao_social, f.cnpj, u.nome AS usuario
                        FROM entradas e LEFT JOIN fornecedores f ON f.id=e.fornecedor_id
                        LEFT JOIN usuarios u ON u.id=e.usuario_id WHERE e.id=?""", (entrada_id,))
    if entrada_row is None:
        flash("Entrada não encontrada.", "erro")
        return redirect(url_for("estoque.index", aba="entradas"))
    itens = todos(
        """SELECT l.*, p.nome, p.codigo FROM lotes l
           JOIN produtos p ON p.id = l.produto_id
           WHERE COALESCE(l.nota_fiscal,'') = COALESCE(?, '')
             AND COALESCE(l.fornecedor_id, 0) = COALESCE(?, 0)
           ORDER BY p.nome COLLATE NOCASE""", (entrada_row["numero"], entrada_row["fornecedor_id"]))
    if not itens:
        itens = todos(
            """SELECT m.produto_id AS produto_id, p.nome, p.codigo, m.quantidade,
                      COALESCE(m.ref_id, m.id) AS lote, m.criado_em, p.preco_custo
               FROM movimentacoes m JOIN produtos p ON p.id = m.produto_id
               WHERE m.tipo_ref = 'entrada' AND m.ref_id = ?""", (entrada_id,))
    return render_template("estoque/entrada_detalhe.html", entrada=entrada_row, itens=itens)


@bp.route("/saida", methods=["POST"])
@login_required("estoque")
def saida():
    """Baixa manual (perda, vencimento, amostra, transferência)."""
    produto_id = int(request.form.get("produto_id") or 0)
    quantidade = int(_numero(request.form.get("quantidade")))
    motivo = request.form.get("motivo") or "perda"
    detalhe = (request.form.get("observacao") or "").strip()
    try:
        if quantidade <= 0:
            raise ErroNegocio("Informe uma quantidade maior que zero.")
        if motivo == "ajuste":
            raise ErroNegocio("Use o ajuste de inventário na ficha do produto.")
        baixar_estoque(produto_id, quantidade, motivo,
                       usuario_id=valor_de(g.get("usuario"), "id"),
                       observacao=detalhe or motivo.capitalize())
        registrar_acao("saida_estoque", "produtos", produto_id,
                       f"{motivo}: {quantidade} un. - {detalhe}")
        flash(f"Baixa de {quantidade} unidade(s) registrada ({motivo}).", "ok")
    except (ErroNegocio, ValueError, TypeError) as erro:
        flash(str(erro), "erro")
    return redirect(request.referrer or url_for("estoque.index"))


@bp.route("/devolucao", methods=["POST"])
@login_required("estoque")
def devolucao():
    """Devolução de cliente ao estoque."""
    produto_id = int(request.form.get("produto_id") or 0)
    quantidade = int(_numero(request.form.get("quantidade")))
    try:
        if quantidade <= 0:
            raise ErroNegocio("Informe uma quantidade maior que zero.")
        devolver_estoque(produto_id, quantidade, valor_de(g.get("usuario"), "id"),
                         observacao=(request.form.get("observacao") or "Devolução de cliente"))
        registrar_acao("devolucao", "produtos", produto_id, f"Devolução de {quantidade} un.")
        flash(f"{quantidade} unidade(s) devolvida(s) ao estoque.", "ok")
    except (ErroNegocio, ValueError, TypeError) as erro:
        flash(str(erro), "erro")
    return redirect(request.referrer or url_for("estoque.index"))


@bp.route("/lote/<int:lote_id>/ajuste", methods=["POST"])
@login_required("estoque")
def ajustar_lote(lote_id):
    lote = um("SELECT * FROM lotes WHERE id = ?", (lote_id,))
    if not lote:
        flash("Lote não encontrado.", "erro")
        return redirect(url_for("estoque.index", aba="lotes"))
    nova_qtd = int(_numero(request.form.get("quantidade")))
    delta = nova_qtd - int(lote["quantidade"])
    try:
        if delta == 0:
            flash("Nada a alterar.", "ok")
        elif delta > 0:
            from ..services import entrada_estoque
            entrada_estoque(lote["produto_id"], delta, lote=lote["lote"], validade=lote["validade"],
                            custo=lote["preco_custo"], usuario_id=valor_de(g.get("usuario"), "id"),
                            tipo="ajuste", observacao=f"Ajuste do lote {lote['lote'] or lote['id']}")
        else:
            baixar_estoque(lote["produto_id"], abs(delta), "ajuste",
                           usuario_id=valor_de(g.get("usuario"), "id"),
                           observacao=f"Ajuste do lote {lote['lote'] or lote['id']}")
        registrar_acao("ajuste_lote", "lotes", lote_id, f"Quantidade {lote['quantidade']} -> {nova_qtd}")
        flash("Lote ajustado.", "ok")
    except (ErroNegocio, ValueError) as erro:
        flash(str(erro), "erro")
    return redirect(url_for("estoque.index", aba="lotes"))


@bp.route("/api/sugestao-compra")
@login_required("estoque")
def sugestao_compra():
    """Lista de reposição com base no estoque mínimo e giro."""
    itens = todos(
        """SELECT p.id, p.codigo, p.nome, p.principio_ativo, p.laboratorio, p.estoque, p.estoque_minimo,
                  p.preco_custo, p.unidade,
                  COALESCE((SELECT SUM(vi.quantidade) FROM venda_itens vi
                            JOIN vendas v ON v.id = vi.venda_id
                            WHERE vi.produto_id = p.id AND v.status='concluida'
                              AND date(v.data) >= date('now','-30 days')), 0) AS giro30
           FROM produtos p WHERE p.ativo=1 AND p.estoque <= p.estoque_minimo
           ORDER BY p.nome""")
    linhas = []
    for i in itens:
        necessario = max(0, int(i["estoque_minimo"]) - int(i["estoque"]))
        giro = int(i["giro30"])
        sugerido = max(necessario, int(giro * 1.2) - int(i["estoque"]))
        linhas.append({
            **dict(i),
            "sugerido": max(sugerido, necessario, 1),
            "custo_total": max(sugerido, necessario, 1) * float(i["preco_custo"] or 0),
        })
    return jsonify({"itens": linhas, "total": round(sum(l["custo_total"] for l in linhas), 2)})
