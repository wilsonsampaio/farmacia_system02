"""Gráficos SVG gerados no servidor (sem dependências externas / internet)."""
from html import escape


def _esc(v):
    return escape(str(v if v is not None else ""))


def line_chart(pontos, rotulos=None, altura=220, cor="#2f7cff", cor_area="rgba(47,124,255,.14)"):
    """
    Gráfico de linha/área suavizado.
    pontos: lista de números. rotulos: rótulos no eixo X (mesmo tamanho).
    """
    pontos = [float(p or 0) for p in pontos] or [0]
    n = len(pontos)
    largura = 900
    pad_esq, pad_dir, pad_topo, pad_base = 54, 16, 16, 34
    w = largura - pad_esq - pad_dir
    h = altura - pad_topo - pad_base
    maximo = max(pontos)
    minimo = min(pontos)
    if maximo == minimo:
        maximo = minimo + 1
    escala = lambda v: pad_topo + h - ((v - minimo) / (maximo - minimo)) * h
    xs = [pad_esq + (i * (w / max(1, n - 1))) for i in range(n)]
    ys = [escala(v) for v in pontos]

    d = f"M {xs[0]:.1f} {ys[0]:.1f}"
    for i in range(1, n):
        xm = (xs[i - 1] + xs[i]) / 2
        d += f" C {xm:.1f} {ys[i-1]:.1f}, {xm:.1f} {ys[i]:.1f}, {xs[i]:.1f} {ys[i]:.1f}"
    area = d + f" L {xs[-1]:.1f} {pad_topo+h} L {xs[0]:.1f} {pad_topo+h} Z"

    grade = ""
    for i in range(5):
        y = pad_topo + (h / 4) * i
        val = maximo - ((maximo - minimo) / 4) * i
        grade += (f'<line x1="{pad_esq}" y1="{y:.1f}" x2="{largura-pad_dir}" y2="{y:.1f}" '
                  f'stroke="currentColor" stroke-opacity=".10" stroke-dasharray="4 5"/>')
        grade += (f'<text x="{pad_esq-8}" y="{y+4:.1f}" text-anchor="end" font-size="11" '
                  f'fill="currentColor" fill-opacity=".55">{_esc(_abreviar(val))}</text>')

    eixo_x = ""
    rotulos = rotulos or [str(i + 1) for i in range(n)]
    passo = max(1, n // 10)
    for i, rot in enumerate(rotulos):
        if i % passo and i != n - 1:
            continue
        eixo_x += (f'<text x="{xs[i]:.1f}" y="{altura-10}" text-anchor="middle" font-size="11" '
                   f'fill="currentColor" fill-opacity=".55">{_esc(rot)}</text>')

    bolinhas = "".join(
        f'<circle cx="{xs[i]:.1f}" cy="{ys[i]:.1f}" r="3.2" fill="{cor}" opacity="0">'
        f'<animate attributeName="opacity" from="0" to="1" dur="0.4s" begin="{i*0.02:.2f}s" fill="freeze"/>'
        f"</circle>"
        for i in range(0, n, max(1, n // 25))
    )

    return (
        f'<svg viewBox="0 0 {largura} {altura}" class="chart-svg" preserveAspectRatio="none" role="img">'
        f"<defs><linearGradient id=\"gradLinha\" x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1\">"
        f'<stop offset="0%" stop-color="{cor}" stop-opacity=".28"/>'
        f'<stop offset="100%" stop-color="{cor}" stop-opacity="0"/></linearGradient></defs>'
        f"{grade}"
        f'<path d="{area}" fill="{cor_area if isinstance(cor_area, str) else "url(#gradLinha)"}" '
        f'fill-opacity=".9"><animate attributeName="opacity" from="0" to="1" dur=".6s" fill="freeze"/></path>'
        f'<path d="{d}" fill="none" stroke="{cor}" stroke-width="2.6" stroke-linecap="round" '
        f'stroke-dasharray="2400" stroke-dashoffset="2400">'
        f'<animate attributeName="stroke-dashoffset" from="2400" to="0" dur="1.1s" fill="freeze"/></path>'
        f"{bolinhas}{eixo_x}</svg>"
    )


def bar_chart(itens, cor="#2f7cff", cor_secundaria="#8b5cf6", altura_barra=26):
    """Itens: [(rotulo, valor)] -> barras horizontais animadas."""
    if not itens:
        return '<p class="vazio">Sem dados no período.</p>'
    maximo = max([v for _, v in itens] or [1]) or 1
    html = '<div class="barras">'
    for i, (rotulo, valor) in enumerate(itens):
        pct = max(1.5, (valor / maximo) * 100)
        cor_barra = cor if i % 2 == 0 else cor_secundaria
        html += (
            f'<div class="barra-linha" title="{_esc(rotulo)}: {_esc(valor)}">'
            f'<span class="barra-rotulo">{_esc(_cortar(rotulo, 34))}</span>'
            f'<span class="barra-trilho" style="--h:{altura_barra}px">'
            f'<span class="barra-fill" style="width:{pct:.1f}%;background:{cor_barra};'
            f'animation-delay:{i*0.06:.2f}s"></span></span>'
            f'<span class="barra-valor">{_esc(_abreviar(valor))}</span>'
            f"</div>"
        )
    return html + "</div>"


def donut(itens, legenda=True):
    """Itens: [(rotulo, valor)] -> rosca com legenda."""
    itens = [(r, float(v or 0)) for r, v in itens if float(v or 0) > 0]
    total = sum(v for _, v in itens)
    if not itens or total <= 0:
        return '<p class="vazio">Sem dados no período.</p>'
    paletas = ["#2f7cff", "#16b364", "#f5a524", "#8b5cf6", "#ef476f", "#06b6d4", "#94a3b8", "#e11d48"]
    cx = cy = 90
    r = 66
    espessura = 26
    circ = 2 * 3.14159265 * r
    angulo = -90
    svg = (
        f'<svg viewBox="0 0 180 180" class="donut-svg" role="img">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="currentColor" stroke-opacity=".08" '
        f'stroke-width="{espessura}"/>'
    )
    for i, (rotulo, valor) in enumerate(itens):
        frac = valor / total
        comprimento = circ * frac
        svg += (
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{paletas[i % len(paletas)]}" '
            f'stroke-width="{espessura}" stroke-linecap="butt" '
            f'stroke-dasharray="0 {circ}" transform="rotate({angulo} {cx} {cy})">'
            f'<animate attributeName="stroke-dasharray" from="0 {circ}" to="{comprimento:.2f} {circ-comprimento:.2f}" '
            f'dur=".9s" begin="{i*0.12:.2f}s" fill="freeze"/></circle>'
        )
        angulo += 360 * frac
    svg += (
        f'<text x="{cx}" y="{cy-2}" text-anchor="middle" font-size="20" font-weight="700" '
        f'fill="currentColor">{_esc(_abreviar(total))}</text>'
        f'<text x="{cx}" y="{cy+18}" text-anchor="middle" font-size="11" fill="currentColor" '
        f'fill-opacity=".6">total</text></svg>'
    )
    if not legenda:
        return svg
    html = '<div class="donut-wrap">' + svg + '<ul class="legenda">'
    for i, (rotulo, valor) in enumerate(itens):
        pct = (valor / total) * 100
        html += (
            f'<li><span class="ponto" style="background:{paletas[i % len(paletas)]}"></span>'
            f'<span class="leg-nome">{_esc(rotulo)}</span>'
            f'<span class="leg-val">{_esc(_abreviar(valor))} · {pct:.0f}%</span></li>'
        )
    html += "</ul></div>"
    return html


def gauge(valor, maximo, cor="#16b364", rotulo=""):
    """Medidor semi-circular (ex.: ocupação do estoque / metas)."""
    maximo = float(maximo or 1) or 1
    pct = max(0.0, min(1.0, float(valor or 0) / maximo))
    raio = 70
    meio = 3.14159265 * raio
    return (
        f'<svg viewBox="0 0 180 105" class="gauge-svg" role="img">'
        f'<path d="M 20 90 A {raio} {raio} 0 0 1 160 90" fill="none" stroke="currentColor" '
        f'stroke-opacity=".12" stroke-width="14" stroke-linecap="round"/>'
        f'<path d="M 20 90 A {raio} {raio} 0 0 1 160 90" fill="none" stroke="{cor}" stroke-width="14" '
        f'stroke-linecap="round" stroke-dasharray="{meio:.1f}" stroke-dashoffset="{meio*(1-pct):.1f}">'
        f'<animate attributeName="stroke-dashoffset" from="{meio:.1f}" to="{meio*(1-pct):.1f}" dur="1s" fill="freeze"/>'
        f"</path>"
        f'<text x="90" y="80" text-anchor="middle" font-size="26" font-weight="700" fill="currentColor">'
        f"{pct*100:.0f}%</text>"
        + (f'<text x="90" y="100" text-anchor="middle" font-size="11" fill="currentColor" fill-opacity=".6">{_esc(rotulo)}</text>' if rotulo else "")
        + "</svg>"
    )


def sparkline(valores, cor="#2f7cff", largura=140, altura=36):
    valores = [float(v or 0) for v in valores] or [0]
    maximo = max(valores) or 1
    minimo = min(valores)
    if maximo == minimo:
        maximo = minimo + 1
    n = len(valores)
    pts = []
    for i, v in enumerate(valores):
        x = (i / max(1, n - 1)) * largura
        y = altura - 3 - ((v - minimo) / (maximo - minimo)) * (altura - 6)
        pts.append(f"{x:.1f},{y:.1f}")
    return (
        f'<svg viewBox="0 0 {largura} {altura}" class="sparkline" aria-hidden="true">'
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="{cor}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def _abreviar(valor):
    v = float(valor or 0)
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.1f}M".replace(".0M", "M")
    if abs(v) >= 1_000:
        return f"{v/1_000:.1f}k".replace(".0k", "k")
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}"


def _cortar(texto, limite):
    texto = str(texto or "")
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"
