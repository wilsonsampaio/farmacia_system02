"""Relatórios gerenciais com filtros por período, totais e exportação em CSV."""
import csv
import io
from datetime import datetime

from flask import (Blueprint, Response, flash, redirect, render_template, request,
                   url_for)

from .. import charts
from ..db import todos, um
from ..security import login_required, registrar_acao
from ..utils import FORMAS_PAGAMENTO, brl, data_iso

bp = Blueprint("relatorios", __name__, url_prefix="/relatorios")

PERIODO_PADRAO = ("", "")


def _periodo():
    de = data_iso(request.args.get("de")) or ""
    ate = data_iso(request.args.get("ate")) or ""
    if not de and not ate:
        ate = datetime.now().strftime("%Y-%m-%d")
        de = (datetime.now().replace(day=1)).strftime("%Y-%m-%d")
    return de, ate


def _intervalo(de, ate, coluna="v.data"):
    """Trecho SQL do período (inclusive)."""
    clausulas, params = [], []
    if de:
        clausulas.append(f"date({coluna}) >= date(?)")
        params.append(de)
    if ate:
        clausulas.append(f"date({coluna}) <= date(?)")
        params.append(ate)
    return (" AND ".join(clausulas) if clausulas else "1=1"), params


# ------------------------------------------------------------------ construtores
def rel_vendas_por_dia(de, ate):
    cond, params = _intervalo(de, ate)
    linhas = todos(
        f"""SELECT date(v.data) AS dia, COUNT(*) AS qtd,
                   COALESCE(SUM(v.subtotal),0) AS subtotal,
                   COALESCE(SUM(v.desconto),0) AS desconto,
                   COALESCE(SUM(v.total),0) AS total
            FROM vendas v WHERE v.status='concluida' AND {cond}
            GROUP BY date(v.data) ORDER BY dia DESC""", tuple(params))
    dados = [dict(l) for l in linhas]
    for d in dados:
        d["ticket"] = (d["total"] / d["qtd"]) if d["qtd"] else 0
    dados.sort(key=lambda d: d["dia"], reverse=True)
    totais = {
        "qtd": sum(d["qtd"] for d in dados),
        "subtotal": sum(d["subtotal"] for d in dados),
        "desconto": sum(d["desconto"] for d in dados),
        "total": sum(d["total"] for d in dados),
    }
    totais["ticket"] = (totais["total"] / totais["qtd"]) if totais["qtd"] else 0
    serie = list(reversed(dados))
    grafico = charts.line_chart([d["total"] for d in serie],
                                [f"{d['dia'][8:10]}/{d['dia'][5:7]}" for d in serie])
    return {
        "titulo": "Vendas por dia",
        "descricao": "Faturamento, quantidade de vendas e ticket médio dia a dia.",
        "colunas": [("dia", "Data", "data"), ("qtd", "Vendas", "num"),
                    ("subtotal", "Subtotal", "moeda"), ("desconto", "Descontos", "moeda"),
                    ("total", "Total", "moeda"), ("ticket", "Ticket médio", "moeda")],
        "linhas": dados, "totais": totais, "grafico": grafico,
        "fim_tabela": True,
    }


def rel_itens_vendidos(de, ate):
    cond, params = _intervalo(de, ate)
    linhas = todos(
        f"""SELECT vi.nome, vi.codigo, COALESCE(p.principio_ativo,'') AS principio_ativo,
                   COALESCE(p.laboratorio,'') AS laboratorio, COALESCE(p.classe_terapeutica,'') AS classe,
                   SUM(vi.quantidade) AS quantidade, SUM(vi.subtotal) AS receita,
                   SUM(vi.quantidade * COALESCE(p.preco_custo,0)) AS custo
            FROM venda_itens vi JOIN vendas v ON v.id=vi.venda_id
            LEFT JOIN produtos p ON p.id=vi.produto_id
            WHERE v.status='concluida' AND {cond}
            GROUP BY vi.produto_id, vi.nome ORDER BY quantidade DESC""", tuple(params))
    dados = [dict(l) for l in linhas]
    total_receita = sum(d["receita"] or 0 for d in dados) or 1
    acumulado = 0
    for i, d in enumerate(dados, 1):
        d["participacao"] = (d["receita"] / total_receita) * 100
        acumulado += d["receita"]
        d["acumulado"] = (acumulado / total_receita) * 100
        d["classe_abc"] = "A" if d["acumulado"] <= 80 else ("B" if d["acumulado"] <= 95 else "C")
        d["lucro"] = (d["receita"] or 0) - (d["custo"] or 0)
    totais = {"quantidade": sum(d["quantidade"] for d in dados),
              "receita": sum(d["receita"] or 0 for d in dados),
              "custo": sum(d["custo"] or 0 for d in dados),
              "lucro": sum(d["lucro"] for d in dados)}
    top = dados[:10]
    return {
        "titulo": "Itens vendidos (curva ABC)",
        "descricao": "Produtos vendidos no período, participação na receita, lucro e classificação ABC.",
        "colunas": [("nome", "Produto", "texto"), ("codigo", "Código", "texto"),
                    ("principio_ativo", "Princípio ativo", "texto"),
                    ("laboratorio", "Laboratório", "texto"),
                    ("quantidade", "Qtd.", "num"), ("receita", "Receita", "moeda"),
                    ("custo", "Custo", "moeda"), ("lucro", "Lucro", "moeda"),
                    ("participacao", "%", "percent"), ("acumulado", "% acum.", "percent"),
                    ("classe_abc", "ABC", "texto")],
        "linhas": dados, "totais": totais,
        "grafico": charts.bar_chart([(d["nome"], d["quantidade"]) for d in top]),
    }


def rel_produtos(de, ate):
    linhas = todos(
        """SELECT p.codigo, p.nome, p.principio_ativo, p.laboratorio, p.classe_terapeutica,
                  p.tarja, p.estoque, p.estoque_minimo, p.preco_custo, p.preco_venda,
                  (p.preco_venda - p.preco_custo) AS margem,
                  CASE WHEN p.preco_custo > 0 THEN ((p.preco_venda - p.preco_custo)/p.preco_custo)*100 ELSE 0 END AS perc_margem
           FROM produtos p WHERE p.ativo=1 ORDER BY p.nome COLLATE NOCASE""")
    dados = [dict(l) for l in linhas]
    for d in dados:
        d["valor_estoque"] = d["estoque"] * d["preco_custo"]
    totais = {"estoque": sum(d["estoque"] for d in dados),
              "valor_estoque": sum(d["valor_estoque"] for d in dados),
              "preco_venda": 0, "margem": 0}
    return {
        "titulo": "Relação de produtos",
        "descricao": "Todos os medicamentos cadastrados com preço, margem e situação de estoque.",
        "colunas": [("codigo", "Código", "texto"), ("nome", "Produto", "texto"),
                    ("principio_ativo", "Princípio ativo", "texto"),
                    ("laboratorio", "Laboratório", "texto"),
                    ("classe_terapeutica", "Classe", "texto"), ("tarja", "Tarja", "texto"),
                    ("estoque", "Estoque", "num"), ("estoque_minimo", "Mín.", "num"),
                    ("preco_custo", "Custo", "moeda"), ("preco_venda", "Venda", "moeda"),
                    ("perc_margem", "Margem %", "percent"), ("valor_estoque", "Valor estoque", "moeda")],
        "linhas": dados, "totais": totais,
    }


def rel_estoque(de, ate):
    linhas = todos(
        """SELECT p.codigo, p.nome, p.principio_ativo, p.laboratorio, p.estoque, p.estoque_minimo,
                  p.localizacao, p.preco_custo, p.preco_venda,
                  p.estoque*p.preco_custo AS valor_custo, p.estoque*p.preco_venda AS valor_venda,
                  CASE WHEN p.estoque<=0 THEN 'Sem estoque'
                       WHEN p.estoque<=p.estoque_minimo THEN 'Baixo' ELSE 'Normal' END AS situacao
           FROM produtos p WHERE p.ativo=1
           ORDER BY CASE WHEN p.estoque<=0 THEN 0 WHEN p.estoque<=p.estoque_minimo THEN 1 ELSE 2 END,
                    p.nome COLLATE NOCASE""")
    dados = [dict(l) for l in linhas]
    totais = {"estoque": sum(d["estoque"] for d in dados),
              "valor_custo": sum(d["valor_custo"] for d in dados),
              "valor_venda": sum(d["valor_venda"] for d in dados)}
    return {
        "titulo": "Posição de estoque",
        "descricao": "Saldo atual por produto com valor de custo e de venda.",
        "colunas": [("codigo", "Código", "texto"), ("nome", "Produto", "texto"),
                    ("laboratorio", "Laboratório", "texto"), ("localizacao", "Local", "texto"),
                    ("estoque", "Saldo", "num"), ("estoque_minimo", "Mínimo", "num"),
                    ("situacao", "Situação", "situacao"),
                    ("valor_custo", "Valor custo", "moeda"), ("valor_venda", "Valor venda", "moeda")],
        "linhas": dados, "totais": totais,
    }


def rel_baixos(de, ate):
    linhas = todos(
        """SELECT p.codigo, p.nome, p.principio_ativo, p.laboratorio, p.estoque, p.estoque_minimo,
                  p.preco_custo, p.unidade,
                  COALESCE((SELECT SUM(vi.quantidade) FROM venda_itens vi JOIN vendas v ON v.id=vi.venda_id
                            WHERE vi.produto_id=p.id AND v.status='concluida'
                              AND date(v.data)>=date('now','-30 days')),0) AS giro30
           FROM produtos p WHERE p.ativo=1 AND p.estoque <= p.estoque_minimo
           ORDER BY p.nome COLLATE NOCASE""")
    dados = [dict(l) for l in linhas]
    for d in dados:
        d["sugestao"] = max(1, d["estoque_minimo"] - d["estoque"], int(d["giro30"] * 1.2) - d["estoque"])
        d["custo_sugestao"] = d["sugestao"] * (d["preco_custo"] or 0)
    totais = {"sugestao": sum(d["sugestao"] for d in dados),
              "custo_sugestao": sum(d["custo_sugestao"] for d in dados)}
    return {
        "titulo": "Produtos para reposição",
        "descricao": "Itens com saldo igual ou inferior ao mínimo, com sugestão de compra.",
        "colunas": [("codigo", "Código", "texto"), ("nome", "Produto", "texto"),
                    ("laboratorio", "Laboratório", "texto"), ("estoque", "Saldo", "num"),
                    ("estoque_minimo", "Mínimo", "num"), ("giro30", "Giro 30d", "num"),
                    ("sugestao", "Comprar", "num"), ("custo_sugestao", "Custo sugerido", "moeda")],
        "linhas": dados, "totais": totais,
    }


def rel_vencimentos(de, ate):
    dias = int((um("SELECT valor FROM parametros WHERE chave='estoque_alerta_dias'") or {"valor": 60})["valor"] or 60)
    linhas = todos(
        """SELECT p.codigo, p.nome, p.laboratorio, l.lote, l.validade, l.quantidade, l.preco_custo,
                  f.razao_social AS fornecedor,
                  CAST(julianday(l.validade)-julianday('now') AS INTEGER) AS dias,
                  l.quantidade*l.preco_custo AS valor
           FROM lotes l JOIN produtos p ON p.id=l.produto_id
           LEFT JOIN fornecedores f ON f.id=l.fornecedor_id
           WHERE l.quantidade>0 AND l.validade IS NOT NULL AND l.validade!=''
             AND date(l.validade) <= date('now', ?)
           ORDER BY date(l.validade)""", (f"+{dias} days",))
    dados = [dict(l) for l in linhas]
    for d in dados:
        d["situacao"] = "Vencido" if (d["dias"] or 0) < 0 else ("Crítico" if (d["dias"] or 999) <= 15 else "Atenção")
    totais = {"quantidade": sum(d["quantidade"] for d in dados),
              "valor": sum(d["valor"] for d in dados)}
    return {
        "titulo": "Validade dos lotes",
        "descricao": f"Lotes que vencem em até {dias} dias (inclui já vencidos).",
        "colunas": [("codigo", "Código", "texto"), ("nome", "Produto", "texto"),
                    ("lote", "Lote", "texto"), ("validade", "Validade", "data"),
                    ("dias", "Dias", "num"), ("situacao", "Situação", "situacao"),
                    ("quantidade", "Qtd.", "num"), ("fornecedor", "Fornecedor", "texto"),
                    ("valor", "Valor", "moeda")],
        "linhas": dados, "totais": totais,
    }


def rel_entradas(de, ate):
    cond, params = _intervalo(de, ate, "e.data_recebimento")
    linhas = todos(
        f"""SELECT e.numero, e.data_recebimento, e.data_emissao, e.total, e.status,
                   f.razao_social AS fornecedor, u.nome AS operador,
                   (SELECT COUNT(*) FROM movimentacoes m WHERE m.tipo_ref='entrada' AND m.ref_id=e.id) AS itens
            FROM entradas e LEFT JOIN fornecedores f ON f.id=e.fornecedor_id
            LEFT JOIN usuarios u ON u.id=e.usuario_id
            WHERE {cond} ORDER BY e.id DESC""", tuple(params))
    dados = [dict(l) for l in linhas]
    totais = {"total": sum(d["total"] or 0 for d in dados), "itens": sum(d["itens"] for d in dados)}
    return {
        "titulo": "Entradas de mercadoria (compras)",
        "descricao": "Notas de entrada recebidas no período.",
        "colunas": [("numero", "Nota", "texto"), ("data_recebimento", "Recebida em", "datahora"),
                    ("fornecedor", "Fornecedor", "texto"), ("itens", "Itens", "num"),
                    ("total", "Total", "moeda"), ("operador", "Operador", "texto"),
                    ("status", "Situação", "texto")],
        "linhas": dados, "totais": totais,
    }


def rel_clientes(de, ate):
    cond, params = _intervalo(de, ate)
    linhas = todos(
        f"""SELECT c.id, c.nome, c.cpf, c.celular, c.cidade,
                   COUNT(v.id) AS compras, COALESCE(SUM(v.total),0) AS total_gasto,
                   c.saldo_credito, c.pontos,
                   MAX(v.data) AS ultima_compra
            FROM clientes c LEFT JOIN vendas v ON v.cliente_id=c.id AND v.status='concluida' AND {cond}
            GROUP BY c.id ORDER BY total_gasto DESC, c.nome""", tuple(params))
    dados = [dict(l) for l in linhas]
    totais = {"compras": sum(d["compras"] for d in dados),
              "total_gasto": sum(d["total_gasto"] for d in dados),
              "saldo_credito": sum(d["saldo_credito"] for d in dados)}
    top = [d for d in dados[:10] if d["total_gasto"]][:10]
    return {
        "titulo": "Clientes",
        "descricao": "Ranking de clientes por valor comprado no período.",
        "colunas": [("nome", "Cliente", "texto"), ("cpf", "CPF", "cpf"),
                    ("celular", "Telefone", "texto"), ("cidade", "Cidade", "texto"),
                    ("compras", "Compras", "num"), ("total_gasto", "Total gasto", "moeda"),
                    ("saldo_credito", "Em aberto", "moeda"), ("pontos", "Pontos", "num"),
                    ("ultima_compra", "Última compra", "datahora")],
        "linhas": dados, "totais": totais,
        "grafico": charts.bar_chart([(d["nome"], round(d["total_gasto"], 2)) for d in top],
                                    cor="#8b5cf6", cor_secundaria="#2f7cff"),
    }


def rel_fichas(de, ate):
    linhas = todos(
        """SELECT c.id AS cliente_id, c.nome, c.cpf, c.celular, c.limite_credito, c.saldo_credito,
                  MIN(f.vencimento) AS primeira_divida,
                  CAST(julianday(MIN(f.vencimento))-julianday('now') AS INTEGER) AS dias
           FROM fichas f JOIN clientes c ON c.id=f.cliente_id
           WHERE f.tipo='lancamento' AND c.saldo_credito > 0
           GROUP BY c.id ORDER BY c.saldo_credito DESC""")
    dados = [dict(l) for l in linhas]
    for d in dados:
        d["situacao"] = "Vencida" if (d["dias"] is not None and d["dias"] < 0) else "Em dia"
    totais = {"saldo_credito": sum(d["saldo_credito"] for d in dados)}
    return {
        "titulo": "Fichas de clientes (contas em aberto)",
        "descricao": "Clientes com saldo devedor na ficha e datas de vencimento.",
        "colunas": [("nome", "Cliente", "texto"), ("cpf", "CPF", "cpf"),
                    ("celular", "Telefone", "texto"), ("saldo_credito", "Saldo devedor", "moeda"),
                    ("limite_credito", "Limite", "moeda"), ("primeira_divida", "1ª dívida", "data"),
                    ("situacao", "Situação", "situacao")],
        "linhas": dados, "totais": totais,
    }


def rel_operadores(de, ate):
    cond, params = _intervalo(de, ate)
    linhas = todos(
        f"""SELECT u.nome AS operador, u.login, u.perfil,
                   COUNT(v.id) AS vendas, COALESCE(SUM(v.total),0) AS total,
                   COALESCE(SUM(v.desconto),0) AS descontos, COALESCE(SUM(v.troco),0) AS troco
            FROM usuarios u LEFT JOIN vendas v ON v.usuario_id=u.id AND v.status='concluida' AND {cond}
            GROUP BY u.id ORDER BY total DESC""", tuple(params))
    dados = [dict(l) for l in linhas]
    for d in dados:
        d["ticket"] = (d["total"] / d["vendas"]) if d["vendas"] else 0
    totais = {"vendas": sum(d["vendas"] for d in dados), "total": sum(d["total"] for d in dados),
              "descontos": sum(d["descontos"] for d in dados)}
    return {
        "titulo": "Desempenho por operador",
        "descricao": "Vendas realizadas por usuário no período.",
        "colunas": [("operador", "Operador", "texto"), ("login", "Login", "texto"),
                    ("perfil", "Perfil", "texto"), ("vendas", "Vendas", "num"),
                    ("total", "Faturamento", "moeda"), ("ticket", "Ticket médio", "moeda"),
                    ("descontos", "Descontos", "moeda")],
        "linhas": dados, "totais": totais,
    }


def rel_formas(de, ate):
    cond, params = _intervalo(de, ate)
    linhas = todos(
        f"""SELECT p.forma, COUNT(*) AS lancamentos, SUM(p.valor) AS total, SUM(p.parcelas) AS parcelas
            FROM pagamentos p JOIN vendas v ON v.id=p.venda_id
            WHERE v.status='concluida' AND {cond}
            GROUP BY p.forma ORDER BY total DESC""", tuple(params))
    dados = [dict(l) for l in linhas]
    nomes = dict(FORMAS_PAGAMENTO)
    for d in dados:
        d["nome"] = nomes.get(d["forma"], d["forma"])
    total = sum(d["total"] for d in dados) or 1
    for d in dados:
        d["participacao"] = (d["total"] / total) * 100
    totais = {"lancamentos": sum(d["lancamentos"] for d in dados),
              "total": sum(d["total"] for d in dados)}
    return {
        "titulo": "Meios de pagamento",
        "descricao": "Distribuição do faturamento por forma de pagamento.",
        "colunas": [("nome", "Forma de pagamento", "texto"), ("lancamentos", "Lançamentos", "num"),
                    ("total", "Total", "moeda"), ("participacao", "Participação", "percent")],
        "linhas": dados, "totais": totais,
        "grafico": charts.donut([(d["nome"], d["total"]) for d in dados]),
    }


def rel_auditoria(de, ate):
    cond, params = _intervalo(de, ate, "a.criado_em")
    linhas = todos(
        f"""SELECT a.criado_em, a.usuario, a.acao, a.tabela, a.detalhes, a.ip
            FROM auditoria a WHERE {cond} ORDER BY a.id DESC LIMIT 2000""", tuple(params))
    dados = [dict(l) for l in linhas]
    totais = {"total": len(dados)}
    return {
        "titulo": "Log de atividades (auditoria)",
        "descricao": "Registro de ações dos usuários (até 2.000 últimas linhas no período).",
        "colunas": [("criado_em", "Data/hora", "datahora"), ("usuario", "Usuário", "texto"),
                    ("acao", "Ação", "texto"), ("tabela", "Módulo", "texto"),
                    ("detalhes", "Detalhes", "texto"), ("ip", "IP", "texto")],
        "linhas": dados, "totais": totais,
    }


def rel_margens(de, ate):
    linhas = todos(
        """SELECT p.codigo, p.nome, p.laboratorio, p.classe_terapeutica, p.preco_custo, p.preco_venda,
                  (p.preco_venda - p.preco_custo) AS lucro_unidade,
                  COALESCE(s.qtd,0) AS vendidos, COALESCE(s.receita,0) AS receita,
                  COALESCE(s.custo,0) AS custo_total,
                  COALESCE(s.receita,0) - COALESCE(s.custo,0) AS lucro
           FROM produtos p
           LEFT JOIN (SELECT vi.produto_id, SUM(vi.quantidade) qtd, SUM(vi.subtotal) receita,
                             SUM(vi.quantidade*COALESCE(p2.preco_custo,0)) custo
                      FROM venda_itens vi JOIN vendas v ON v.id=vi.venda_id
                      LEFT JOIN produtos p2 ON p2.id=vi.produto_id
                      WHERE v.status='concluida' GROUP BY vi.produto_id) s ON s.produto_id=p.id
           WHERE p.ativo=1 ORDER BY lucro DESC""")
    dados = [dict(l) for l in linhas if (l["receita"] or 0) > 0]
    totais = {"receita": sum(d["receita"] for d in dados),
              "custo_total": sum(d["custo_total"] for d in dados),
              "lucro": sum(d["lucro"] for d in dados)}
    return {
        "titulo": "Margem por produto",
        "descricao": "Lucro bruto gerado por cada medicamento vendido.",
        "colunas": [("codigo", "Código", "texto"), ("nome", "Produto", "texto"),
                    ("laboratorio", "Laboratório", "texto"), ("preco_custo", "Custo", "moeda"),
                    ("preco_venda", "Venda", "moeda"), ("lucro_unidade", "Lucro/un.", "moeda"),
                    ("vendidos", "Qtd.", "num"), ("receita", "Receita", "moeda"),
                    ("lucro", "Lucro total", "moeda")],
        "linhas": dados, "totais": totais,
    }


RELATORIOS = {
    "vendas-dia": {"funcao": rel_vendas_por_dia, "perm": "relatorios", "grupo": "Vendas"},
    "itens": {"funcao": rel_itens_vendidos, "perm": "relatorios", "grupo": "Vendas"},
    "formas": {"funcao": rel_formas, "perm": "relatorios", "grupo": "Vendas"},
    "operadores": {"funcao": rel_operadores, "perm": "relatorios", "grupo": "Vendas"},
    "margens": {"funcao": rel_margens, "perm": "relatorios", "grupo": "Vendas"},
    "produtos": {"funcao": rel_produtos, "perm": "relatorios", "grupo": "Cadastros"},
    "estoque": {"funcao": rel_estoque, "perm": "relatorios", "grupo": "Estoque"},
    "baixos": {"funcao": rel_baixos, "perm": "relatorios", "grupo": "Estoque"},
    "vencimentos": {"funcao": rel_vencimentos, "perm": "relatorios", "grupo": "Estoque"},
    "entradas": {"funcao": rel_entradas, "perm": "relatorios", "grupo": "Estoque"},
    "clientes": {"funcao": rel_clientes, "perm": "relatorios", "grupo": "Pessoas"},
    "fichas": {"funcao": rel_fichas, "perm": "fichas", "grupo": "Pessoas"},
    "auditoria": {"funcao": rel_auditoria, "perm": "administracao", "grupo": "Sistema"},
}


TITULOS = {
    "vendas-dia": ("Vendas por dia", "Faturamento dia a dia, quantidade de vendas e ticket médio."),
    "itens": ("Itens vendidos (curva ABC)", "Produtos mais vendidos, participação na receita e classificação ABC."),
    "formas": ("Meios de pagamento", "Como os clientes pagaram no período: dinheiro, cartões, PIX e fichas."),
    "operadores": ("Desempenho por operador", "Vendas e faturamento de cada usuário do sistema."),
    "margens": ("Margem por produto", "Lucro bruto gerado por cada medicamento."),
    "produtos": ("Relação de produtos", "Todos os medicamentos com preços, margens e estoque."),
    "estoque": ("Posição de estoque", "Saldo atual por produto com valores de custo e venda."),
    "baixos": ("Produtos para reposição", "Itens abaixo do estoque mínimo com sugestão de compra."),
    "vencimentos": ("Validade dos lotes", "Lotes próximos do vencimento e já vencidos."),
    "entradas": ("Entradas de mercadoria", "Notas de compra recebidas no período."),
    "clientes": ("Clientes", "Ranking de clientes por valor comprado."),
    "fichas": ("Fichas de clientes", "Contas em aberto e datas de vencimento."),
    "auditoria": ("Log de atividades", "Registro das ações realizadas pelos usuários."),
}


@bp.route("/")
@login_required("relatorios")
def index():
    grupos = {}
    for slug, info in RELATORIOS.items():
        titulo, descricao = TITULOS.get(slug, (slug, ""))
        grupos.setdefault(info["grupo"], []).append({"slug": slug, "titulo": titulo,
                                                     "descricao": descricao, "perm": info["perm"]})
    hoje = datetime.now().strftime("%Y-%m-%d")
    de, ate = _periodo()
    return render_template("relatorios/index.html", grupos=grupos, hoje=hoje, de=de, ate=ate,
                           so_admin=(g_usuario_perfil() == "admin"))


def g_usuario_perfil():
    from flask import g
    usuario = g.get("usuario")
    if not usuario:
        return ""
    return usuario["perfil"] if "perfil" in usuario.keys() else ""


@bp.route("/<slug>")
@login_required("relatorios")
def relatorio(slug):
    info = RELATORIOS.get(slug)
    if info is None:
        flash("Relatório não encontrado.", "erro")
        return redirect(url_for("relatorios.index"))
    if slug == "auditoria" and g_usuario_perfil() != "admin":
        flash("Apenas administradores podem consultar o log de atividades.", "erro")
        return redirect(url_for("relatorios.index"))
    de, ate = _periodo()
    try:
        relatorio_dados = info["funcao"](de, ate)
    except Exception as erro:  # noqa: BLE001
        flash(f"Erro ao gerar o relatório: {erro}", "erro")
        return redirect(url_for("relatorios.index"))
    registrar_acao("relatorio", "relatorios", None, f"{relatorio_dados['titulo']} ({de} a {ate})")
    titulo, descricao = TITULOS.get(slug, (relatorio_dados["titulo"], relatorio_dados["descricao"]))
    return render_template("relatorios/relatorio.html", rel=relatorio_dados, slug=slug,
                           de=de, ate=ate, registros=len(relatorio_dados["linhas"]),
                           titulo=titulo, descricao=descricao)


@bp.route("/<slug>/csv")
@login_required("relatorios")
def relatorio_csv(slug):
    info = RELATORIOS.get(slug)
    if info is None:
        flash("Relatório não encontrado.", "erro")
        return redirect(url_for("relatorios.index"))
    if slug == "auditoria" and g_usuario_perfil() != "admin":
        flash("Apenas administradores podem consultar o log de atividades.", "erro")
        return redirect(url_for("relatorios.index"))
    de, ate = _periodo()
    dados = info["funcao"](de, ate)
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";")
    escritor.writerow([c[1] for c in dados["colunas"]])
    for linha in dados["linhas"]:
        escritor.writerow([linha.get(c[0], "") for c in dados["colunas"]])
    conteudo = "\ufeff" + saida.getvalue()
    nome = f"{slug}_{de or 'inicio'}_{ate or 'hoje'}.csv"
    registrar_acao("exportar_csv", "relatorios", None, f"{dados['titulo']} -> {nome}")
    return Response(conteudo, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={nome}"})
