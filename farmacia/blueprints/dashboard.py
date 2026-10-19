"""Dashboard executivo com indicadores, gráficos e alertas."""
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request

from .. import charts
from ..db import get_db, todos, um
from ..security import login_required
from ..utils import brl

bp = Blueprint("dashboard", __name__)


def _serie_vendas(dias=30):
    db = get_db()
    linhas = db.execute(
        """SELECT date(data) AS dia, COUNT(*) AS qtd, SUM(total) AS total
           FROM vendas WHERE status = 'concluida' AND date(data) >= date('now', ?)
           GROUP BY date(data) ORDER BY dia""",
        (f"-{int(dias) - 1} days",),
    ).fetchall()
    mapa = {l["dia"]: l for l in linhas}
    pontos, rotulos = [], []
    hoje = datetime.now().date()
    for i in range(int(dias) - 1, -1, -1):
        dia = (hoje - timedelta(days=i)).isoformat()
        linha = mapa.get(dia)
        pontos.append(float(linha["total"] or 0) if linha else 0)
        rotulos.append(f"{dia[8:10]}/{dia[5:7]}")
    return pontos, rotulos


def _kpis():
    db = get_db()
    hoje = datetime.now().strftime("%Y-%m-%d")
    ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    mes = datetime.now().strftime("%Y-%m-01")

    v_hoje = db.execute(
        "SELECT COUNT(*) q, COALESCE(SUM(total),0) t FROM vendas WHERE status='concluida' AND date(data)=?",
        (hoje,)).fetchone()
    v_ontem = db.execute(
        "SELECT COALESCE(SUM(total),0) t FROM vendas WHERE status='concluida' AND date(data)=?",
        (ontem,)).fetchone()
    v_mes = db.execute(
        "SELECT COUNT(*) q, COALESCE(SUM(total),0) t FROM vendas WHERE status='concluida' AND data>=?",
        (mes,)).fetchone()
    v_mes_passado = db.execute(
        """SELECT COALESCE(SUM(total),0) t FROM vendas WHERE status='concluida'
           AND date(data) >= date(?, '-1 month') AND date(data) < date(?, '-1 month')""",
        (mes, mes)).fetchone()
    itens_hoje = db.execute(
        """SELECT COALESCE(SUM(vi.quantidade),0) q FROM venda_itens vi
           JOIN vendas v ON v.id = vi.venda_id
           WHERE v.status='concluida' AND date(v.data)=?""", (hoje,)).fetchone()
    clientes_novos = db.execute(
        "SELECT COUNT(*) FROM clientes WHERE date(criado_em) >= date(?, '-1 month')", (mes,)).fetchone()[0]
    produtos_ativos = db.execute("SELECT COUNT(*) FROM produtos WHERE ativo=1").fetchone()[0]
    estoque_normal = db.execute(
        "SELECT COUNT(*) FROM produtos WHERE ativo=1 AND estoque > estoque_minimo").fetchone()[0]

    ticket = (v_mes["t"] / v_mes["q"]) if v_mes["q"] else 0
    variacao = 0.0
    if v_ontem["t"]:
        variacao = ((v_hoje["t"] - v_ontem["t"]) / v_ontem["t"]) * 100

    return {
        "vendas_hoje": v_hoje["t"], "qtd_hoje": v_hoje["q"],
        "vendas_ontem": v_ontem["t"], "variacao": variacao,
        "vendas_mes": v_mes["t"], "qtd_mes": v_mes["q"],
        "mes_passado": v_mes_passado["t"],
        "ticket": ticket,
        "itens_hoje": itens_hoje["q"],
        "clientes_novos": clientes_novos,
        "produtos_ativos": produtos_ativos,
        "estoque_adequado": estoque_normal,
        "crescimento": (((v_mes["t"] - v_mes_passado["t"]) / v_mes_passado["t"]) * 100)
        if v_mes_passado["t"] else (100.0 if v_mes["t"] else 0.0),
    }


@bp.route("/")
@login_required("dashboard")
def index():
    db = get_db()
    kpis = _kpis()
    pontos, rotulos = _serie_vendas(30)

    top_produtos = todos(
        """SELECT vi.nome, SUM(vi.quantidade) AS qtd, SUM(vi.subtotal) AS valor
           FROM venda_itens vi JOIN vendas v ON v.id = vi.venda_id
           WHERE v.status='concluida' AND date(v.data) >= date('now','-29 days')
           GROUP BY vi.nome ORDER BY qtd DESC LIMIT 10""")

    formas = todos(
        """SELECT CASE p.forma WHEN 'debito' THEN 'Cartão débito' WHEN 'credito' THEN 'Cartão crédito'
                    WHEN 'dinheiro' THEN 'Dinheiro' WHEN 'pix' THEN 'PIX'
                    WHEN 'ficha' THEN 'Ficha do cliente' ELSE p.forma END AS forma,
                  SUM(p.valor) AS total
           FROM pagamentos p JOIN vendas v ON v.id = p.venda_id
           WHERE v.status='concluida' AND date(v.data) >= date('now','-29 days')
           GROUP BY forma ORDER BY total DESC""")

    por_hora = todos(
        """SELECT substr(data,12,2) AS hora, COUNT(*) AS qtd, SUM(total) AS total
           FROM vendas WHERE status='concluida' AND date(data)=date('now')
           GROUP BY hora ORDER BY hora""")

    top_labs = todos(
        """SELECT COALESCE(p.laboratorio,'Sem laboratório') AS lab, SUM(vi.quantidade) AS qtd,
                  SUM(vi.subtotal) AS valor
           FROM venda_itens vi
           JOIN vendas v ON v.id = vi.venda_id
           LEFT JOIN produtos p ON p.id = vi.produto_id
           WHERE v.status='concluida' AND date(v.data) >= date('now','-29 days')
           GROUP BY lab ORDER BY valor DESC LIMIT 8""")

    estoque_baixo = todos(
        """SELECT id, nome, codigo, estoque, estoque_minimo, principio_ativo, laboratorio
           FROM produtos WHERE ativo=1 AND estoque <= estoque_minimo
           ORDER BY (estoque - estoque_minimo), estoque LIMIT 8""")

    vencimentos = todos(
        """SELECT l.produto_id, p.nome, l.lote, l.validade, l.quantidade,
                  CAST(julianday(l.validade) - julianday('now') AS INTEGER) AS dias
           FROM lotes l JOIN produtos p ON p.id = l.produto_id
           WHERE l.quantidade > 0 AND l.validade IS NOT NULL AND l.validade != ''
             AND date(l.validade) <= date('now', '+' || COALESCE((SELECT valor FROM parametros WHERE chave='estoque_alerta_dias'), '60') || ' days')
           ORDER BY date(l.validade) LIMIT 8""")

    ultimas_vendas = todos(
        """SELECT v.*, c.nome AS cliente, u.nome AS operador
           FROM vendas v LEFT JOIN clientes c ON c.id = v.cliente_id
           LEFT JOIN usuarios u ON u.id = v.usuario_id
           ORDER BY v.id DESC LIMIT 8""")

    movimentacoes = todos(
        """SELECT m.*, p.nome AS produto, u.nome AS usuario
           FROM movimentacoes m JOIN produtos p ON p.id = m.produto_id
           LEFT JOIN usuarios u ON u.id = m.usuario_id
           ORDER BY m.id DESC LIMIT 8""")

    vencidas = todos(
        """SELECT c.id, c.nome, c.saldo_credito, MIN(f.vencimento) AS vencimento
           FROM fichas f JOIN clientes c ON c.id = f.cliente_id
           WHERE f.tipo='lancamento' AND f.vencimento IS NOT NULL AND date(f.vencimento) < date('now')
             AND c.saldo_credito > 0
           GROUP BY c.id ORDER BY vencimento LIMIT 6""")

    distribuicao_classe = todos(
        """SELECT COALESCE(p.classe_terapeutica,'Outros') AS classe, SUM(vi.subtotal) AS valor
           FROM venda_itens vi JOIN vendas v ON v.id=vi.venda_id
           LEFT JOIN produtos p ON p.id = vi.produto_id
           WHERE v.status='concluida' AND date(v.data) >= date('now','-29 days')
           GROUP BY classe ORDER BY valor DESC LIMIT 6""")

    try:
        meta_diaria = float((um("SELECT valor FROM parametros WHERE chave='meta_diaria'") or {"valor": 0})["valor"] or 0)
    except (TypeError, ValueError, KeyError):
        meta_diaria = 0.0
    meta_diaria = meta_diaria or 2000.0

    return render_template(
        "dashboard.html",
        kpis=kpis,
        grafico_linha=charts.line_chart(pontos, rotulos),
        grafico_top=charts.bar_chart([(f"{l['nome']}", l["qtd"]) for l in top_produtos]),
        grafico_formas=charts.donut([(f["forma"], f["total"]) for f in formas]),
        grafico_labs=charts.bar_chart([(f["lab"], round(f["valor"] or 0, 2)) for f in top_labs],
                                      cor="#16b364", cor_secundaria="#06b6d4"),
        grafico_horas=charts.line_chart(
            [float(h["total"] or 0) for h in por_hora],
            [f"{h['hora']}h" for h in por_hora] or ["-"],
            altura=170, cor="#8b5cf6"),
        grafico_classe=charts.donut([(d["classe"], d["valor"]) for d in distribuicao_classe]),
        meta=charts.gauge(kpis["vendas_hoje"], meta_diaria, "#16b364", "meta diária"),
        meta_diaria=meta_diaria,
        top_produtos=top_produtos,
        top_labs=top_labs,
        formas=formas,
        estoque_baixo=estoque_baixo,
        vencimentos=vencimentos,
        ultimas_vendas=ultimas_vendas,
        movimentacoes=movimentacoes,
        vencidas=vencidas,
        total_estoque_baixo=len(estoque_baixo),
        brl=brl,
        periodos={"30": 30, "7": 7},
    )


@bp.route("/api/resumo")
@login_required("dashboard")
def api_resumo():
    kpis = _kpis()
    pontos, _ = _serie_vendas(7)
    return {"kpis": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in kpis.items()},
            "serie7": pontos}
