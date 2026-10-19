"""Regras de negócio: estoque, vendas, fichas de clientes e entradas de mercadoria."""
from datetime import datetime

from flask import g

from .db import agora, get_db, inserir, transacao, um
from .utils import valor_de


class ErroNegocio(Exception):
    """Erro de regra de negócio (mensagem amigável exibida na interface)."""


# --------------------------------------------------------------------------- ESTOQUE
def _mover(produto_id, tipo, quantidade, saldo, usuario_id=None, tipo_ref=None, ref_id=None, observacao=""):
    inserir(
        "movimentacoes",
        {
            "produto_id": produto_id,
            "tipo": tipo,
            "quantidade": quantidade,
            "saldo_apos": saldo,
            "tipo_ref": tipo_ref,
            "ref_id": ref_id,
            "usuario_id": usuario_id,
            "observacao": observacao,
        },
    )


def saldo_produto(produto_id):
    row = um("SELECT estoque FROM produtos WHERE id = ?", (produto_id,))
    return int(row["estoque"]) if row else 0


def listar_lotes(produto_id):
    db = get_db()
    return db.execute(
        """SELECT * FROM lotes WHERE produto_id = ? AND quantidade > 0
           ORDER BY (validade IS NULL OR validade = ''), validade, id""",
        (produto_id,),
    ).fetchall()


def entrada_estoque(produto_id, quantidade, lote=None, validade=None, custo=0,
                    fornecedor_id=None, nota_fiscal=None, usuario_id=None,
                    tipo="entrada", ref_id=None, observacao=""):
    """Entra mercadoria: cria/atualiza o lote e soma o saldo do produto."""
    quantidade = int(quantidade)
    if quantidade <= 0:
        raise ErroNegocio("A quantidade da entrada deve ser maior que zero.")
    db = get_db()
    with transacao():
        existente = None
        if lote:
            existente = db.execute(
                "SELECT * FROM lotes WHERE produto_id = ? AND COALESCE(lote,'') = ? AND COALESCE(validade,'') = COALESCE(?, '')",
                (produto_id, lote, validade),
            ).fetchone()
        if existente:
            db.execute(
                "UPDATE lotes SET quantidade = quantidade + ?, preco_custo = ? WHERE id = ?",
                (quantidade, custo or existente["preco_custo"], existente["id"]),
            )
        else:
            db.execute(
                """INSERT INTO lotes (produto_id, lote, validade, quantidade, preco_custo, fornecedor_id, nota_fiscal)
                   VALUES (?,?,?,?,?,?,?)""",
                (produto_id, lote, validade, quantidade, custo or 0, fornecedor_id, nota_fiscal),
            )
        saldo = db.execute("SELECT estoque FROM produtos WHERE id = ?", (produto_id,)).fetchone()[0] + quantidade
        db.execute("UPDATE produtos SET estoque = ?, atualizado_em = ? WHERE id = ?",
                   (saldo, agora(), produto_id))
        if custo:
            db.execute("UPDATE produtos SET preco_custo = ? WHERE id = ?", (custo, produto_id))
        _mover(produto_id, tipo, quantidade, saldo, usuario_id, "entrada", ref_id, observacao)
    return saldo


def baixar_estoque(produto_id, quantidade, tipo="venda", usuario_id=None, tipo_ref=None,
                   ref_id=None, observacao=""):
    """Baixa o saldo do produto usando FIFO (lotes de validade mais próxima primeiro)."""
    quantidade = int(quantidade)
    if quantidade <= 0:
        raise ErroNegocio("Quantidade inválida para baixa de estoque.")
    db = get_db()
    produto = db.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,)).fetchone()
    if produto is None:
        raise ErroNegocio("Produto não encontrado.")
    if produto["estoque"] < quantidade:
        raise ErroNegocio(
            f"Estoque insuficiente de '{produto['nome']}' "
            f"(disponível: {produto['estoque']}, solicitado: {quantidade})."
        )
    with transacao():
        restante = quantidade
        lotes = db.execute(
            """SELECT id, quantidade FROM lotes WHERE produto_id = ? AND quantidade > 0
               ORDER BY (validade IS NULL OR validade = ''), validade, id""",
            (produto_id,),
        ).fetchall()
        for lote in lotes:
            if restante <= 0:
                break
            tirar = min(restante, lote["quantidade"])
            db.execute("UPDATE lotes SET quantidade = quantidade - ? WHERE id = ?", (tirar, lote["id"]))
            restante -= tirar
        saldo = produto["estoque"] - quantidade
        db.execute("UPDATE produtos SET estoque = ?, atualizado_em = ? WHERE id = ?", (saldo, agora(), produto_id))
        _mover(produto_id, tipo, -quantidade, saldo, usuario_id, tipo_ref, ref_id, observacao)
    return saldo


def devolver_estoque(produto_id, quantidade, usuario_id=None, tipo_ref=None, ref_id=None, observacao=""):
    """Devolve mercadoria ao estoque (cancelamento de venda / devolução de cliente)."""
    quantidade = int(quantidade)
    db = get_db()
    produto = db.execute("SELECT id FROM produtos WHERE id = ?", (produto_id,)).fetchone()
    if produto is None:
        return 0
    with transacao():
        db.execute(
            """INSERT INTO lotes (produto_id, lote, validade, quantidade, preco_custo)
               VALUES (?, 'DEVOLUCAO', NULL, ?, COALESCE((SELECT preco_custo FROM produtos WHERE id = ?), 0))""",
            (produto_id, quantidade, produto_id),
        )
        saldo = db.execute("SELECT estoque FROM produtos WHERE id = ?", (produto_id,)).fetchone()[0] + quantidade
        db.execute("UPDATE produtos SET estoque = ?, atualizado_em = ? WHERE id = ?", (saldo, agora(), produto_id))
        _mover(produto_id, "devolucao", quantidade, saldo, usuario_id, tipo_ref, ref_id, observacao)
    return saldo


def ajustar_estoque(produto_id, novo_saldo, motivo="", usuario_id=None, tipo_ref=None):
    """Ajuste de inventário: força o saldo para um valor novo."""
    db = get_db()
    produto = db.execute("SELECT estoque FROM produtos WHERE id = ?", (produto_id,)).fetchone()
    if produto is None:
        raise ErroNegocio("Produto não encontrado.")
    atual = produto["estoque"]
    novo_saldo = int(novo_saldo)
    delta = novo_saldo - atual
    with transacao():
        if delta > 0:
            db.execute(
                """INSERT INTO lotes (produto_id, lote, validade, quantidade, preco_custo)
                   VALUES (?, 'AJUSTE', NULL, ?, COALESCE((SELECT preco_custo FROM produtos WHERE id = ?), 0))""",
                (produto_id, delta, produto_id),
            )
        elif delta < 0:
            restante = abs(delta)
            lotes = db.execute(
                """SELECT id, quantidade FROM lotes WHERE produto_id = ? AND quantidade > 0
                   ORDER BY (validade IS NULL OR validade = ''), validade, id""",
                (produto_id,),
            ).fetchall()
            for lote in lotes:
                if restante <= 0:
                    break
                tirar = min(restante, lote["quantidade"])
                db.execute("UPDATE lotes SET quantidade = quantidade - ? WHERE id = ?", (tirar, lote["id"]))
                restante -= tirar
        db.execute("UPDATE produtos SET estoque = ?, atualizado_em = ? WHERE id = ?", (novo_saldo, agora(), produto_id))
        _mover(produto_id, "ajuste", delta, novo_saldo, usuario_id, "ajuste", tipo_ref, motivo)
    return delta


def registrar_entrada_nota(fornecedor_id, itens, usuario_id=None, numero=None, data_emissao=None,
                           observacao="", total=None):
    """
    Registra uma nota de entrada com vários itens.
    itens: [{'produto_id', 'quantidade', 'lote', 'validade', 'preco_unitario'}]
    """
    if not itens:
        raise ErroNegocio("A entrada não pode estar vazia.")
    db = get_db()
    soma = sum(float(i.get("preco_unitario") or 0) * int(i.get("quantidade") or 0) for i in itens)
    with transacao():
        entrada_id = inserir(
            "entradas",
            {
                "numero": numero or proximo_numero("entrada"),
                "fornecedor_id": fornecedor_id,
                "data_emissao": data_emissao,
                "usuario_id": usuario_id,
                "total": float(total) if total is not None else soma,
                "observacao": observacao,
            },
        )
        for item in itens:
            entrada_estoque(
                produto_id=item["produto_id"],
                quantidade=int(item["quantidade"]),
                lote=item.get("lote"),
                validade=item.get("validade"),
                custo=float(item.get("preco_unitario") or 0),
                fornecedor_id=fornecedor_id,
                nota_fiscal=numero,
                usuario_id=usuario_id,
                ref_id=entrada_id,
                observacao=f"NF {numero or entrada_id}",
            )
        db.execute("UPDATE entradas SET total = ? WHERE id = ?", (soma, entrada_id))
    from .security import registrar_acao
    registrar_acao("entrada_nota", "entradas", entrada_id,
                   f"Entrada de {len(itens)} item(ns), total R$ {soma:,.2f}")
    return entrada_id, soma


def proximo_numero(tipo):
    db = get_db()
    ano = datetime.now().year
    if tipo == "venda":
        total = db.execute("SELECT COUNT(*) FROM vendas WHERE strftime('%Y', data) = ?",
                           (str(ano),)).fetchone()[0]
        return f"V{ano}-{total + 1:06d}"
    total = db.execute("SELECT COUNT(*) FROM entradas WHERE strftime('%Y', COALESCE(data_recebimento, criado_em)) = ?",
                       (str(ano),)).fetchone()[0]
    return f"E{ano}-{total + 1:06d}"


# --------------------------------------------------------------------------- VENDAS
def criar_venda(dados, usuario):
    """
    Conclui uma venda completa em uma única transação.

    dados = {
      'cliente_id': int|None,
      'itens': [{'produto_id', 'quantidade', 'preco_unitario', 'desconto'}],
      'desconto': float (desconto total),
      'pagamentos': [{'forma', 'valor', 'parcelas'}],
      'valor_recebido': float (dinheiro entregue, opcional),
      'terminal': str, 'observacao': str
    }
    """
    itens = dados.get("itens") or []
    if not itens:
        raise ErroNegocio("O carrinho está vazio. Adicione produtos para concluir a venda.")
    pagamentos = dados.get("pagamentos") or []
    db = get_db()
    usuario_id = valor_de(usuario, "id") if usuario else None

    # valida e calcula
    linhas = []
    subtotal = 0.0
    for item in itens:
        produto = db.execute("SELECT * FROM produtos WHERE id = ?", (item.get("produto_id"),)).fetchone()
        if produto is None:
            raise ErroNegocio("Produto inválido no carrinho.")
        if not produto["ativo"]:
            raise ErroNegocio(f"O produto '{produto['nome']}' está inativo.")
        qtd = int(item.get("quantidade") or 0)
        if qtd <= 0:
            raise ErroNegocio(f"Quantidade inválida para '{produto['nome']}'.")
        preco = float(item.get("preco_unitario") if item.get("preco_unitario") is not None else produto["preco_venda"])
        desc_item = float(item.get("desconto") or 0)
        if desc_item < 0 or desc_item > preco * qtd:
            raise ErroNegocio(f"Desconto inválido para '{produto['nome']}'.")
        bruto = preco * qtd
        linhas.append({
            "produto": produto, "qtd": qtd, "preco": preco,
            "desconto": desc_item, "subtotal": bruto - desc_item,
        })
        subtotal += bruto - desc_item

    desconto_total = float(dados.get("desconto") or 0)
    if desconto_total < 0 or desconto_total > subtotal + 0.001:
        raise ErroNegocio("Desconto total inválido.")
    total = max(0.0, subtotal - desconto_total)
    recebido = sum(float(p.get("valor") or 0) for p in pagamentos)
    fiado = round(total - recebido, 2)

    if fiado > 0.009:
        cliente_id = dados.get("cliente_id")
        if not cliente_id:
            raise ErroNegocio("Para vender na ficha do cliente é necessário informar o cliente.")
        cliente = db.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        if cliente is None:
            raise ErroNegocio("Cliente não encontrado.")
        limite = float(cliente["limite_credito"] or 0)
        saldo_atual = float(cliente["saldo_credito"] or 0)
        if limite > 0 and saldo_atual + fiado > limite + 0.001:
            raise ErroNegocio(
                f"Limite de crédito do cliente excedido (disponível: "
                f"{'R$ ' + format(limite - saldo_atual, ',.2f')})."
            )
    elif fiado < -0.009:
        # valores a maior em pagamento => troco
        pass

    # ---- transação
    with transacao():
        for linha in linhas:
            disponivel = db.execute("SELECT estoque FROM produtos WHERE id = ?",
                                    (linha["produto"]["id"],)).fetchone()[0]
            if disponivel < linha["qtd"]:
                raise ErroNegocio(
                    f"Estoque insuficiente de '{linha['produto']['nome']}' "
                    f"(disponível: {disponivel}, solicitado: {linha['qtd']})."
                )

        venda_id = inserir(
            "vendas",
            {
                "numero": "TEMP",
                "cliente_id": dados.get("cliente_id"),
                "subtotal": round(subtotal, 2),
                "desconto": round(desconto_total, 2),
                "total": round(total, 2),
                "valor_pago": round(recebido, 2),
                "troco": round(max(0.0, recebido - total), 2),
                "forma_pagamento": (pagamentos[0]["forma"] if pagamentos else "dinheiro"),
                "terminal": dados.get("terminal"),
                "observacao": dados.get("observacao"),
                "usuario_id": usuario_id,
            },
        )
        numero = proximo_numero("venda")
        db.execute("UPDATE vendas SET numero = ? WHERE id = ?", (numero, venda_id))

        for linha in linhas:
            inserir(
                "venda_itens",
                {
                    "venda_id": venda_id,
                    "produto_id": linha["produto"]["id"],
                    "nome": linha["produto"]["nome"],
                    "codigo": linha["produto"]["codigo"],
                    "quantidade": linha["qtd"],
                    "preco_unitario": round(linha["preco"], 2),
                    "desconto": round(linha["desconto"], 2),
                    "subtotal": round(linha["subtotal"], 2),
                },
            )
            baixar_estoque(linha["produto"]["id"], linha["qtd"], "venda", usuario_id,
                           "venda", venda_id, f"Venda {numero}")

        for pg in pagamentos:
            if float(pg.get("valor") or 0) <= 0:
                continue
            inserir(
                "pagamentos",
                {
                    "venda_id": venda_id,
                    "forma": pg.get("forma") or "dinheiro",
                    "valor": round(float(pg["valor"]), 2),
                    "parcelas": int(pg.get("parcelas") or 1),
                },
            )

        if fiado > 0.009:
            cliente_id = dados.get("cliente_id")
            saldo_novo = float(db.execute("SELECT saldo_credito FROM clientes WHERE id = ?",
                                          (cliente_id,)).fetchone()[0]) + fiado
            db.execute("UPDATE clientes SET saldo_credito = ?, atualizado_em = ? WHERE id = ?",
                       (round(saldo_novo, 2), agora(), cliente_id))
            inserir(
                "fichas",
                {
                    "cliente_id": cliente_id,
                    "venda_id": venda_id,
                    "tipo": "lancamento",
                    "valor": round(fiado, 2),
                    "saldo": round(saldo_novo, 2),
                    "descricao": f"Compra na ficha - venda {numero}",
                    "vencimento": _vencimento_ficha(),
                    "usuario_id": usuario_id,
                },
            )
        elif fiado < -0.009:
            db.execute("UPDATE vendas SET troco = ? WHERE id = ?", (round(-fiado, 2), venda_id))

        if dados.get("cliente_id"):
            db.execute("UPDATE clientes SET pontos = pontos + CAST(? AS INTEGER), atualizado_em = ? WHERE id = ?",
                       (int(total // 10), agora(), dados.get("cliente_id")))

    from .security import registrar_acao
    if usuario_id:
        registrar_acao("venda", "vendas", venda_id, f"Venda {numero} no valor de R$ {total:,.2f}")
    return {"id": venda_id, "numero": numero, "total": round(total, 2),
            "troco": round(max(0.0, recebido - total), 2), "fiado": max(0.0, fiado)}


def _vencimento_ficha(dias=30):
    from datetime import timedelta
    return (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")


def cancelar_venda(venda_id, usuario, motivo=""):
    """Cancela a venda, devolvendo toda a mercadoria ao estoque."""
    db = get_db()
    venda = db.execute("SELECT * FROM vendas WHERE id = ?", (venda_id,)).fetchone()
    if venda is None:
        raise ErroNegocio("Venda não encontrada.")
    if venda["status"] == "cancelada":
        raise ErroNegocio("Esta venda já está cancelada.")
    usuario_id = valor_de(usuario, "id") if usuario else None
    with transacao():
        itens = db.execute("SELECT * FROM venda_itens WHERE venda_id = ?", (venda_id,)).fetchall()
        for item in itens:
            if item["produto_id"]:
                devolver_estoque(item["produto_id"], item["quantidade"], usuario_id,
                                 "venda", venda_id, f"Cancelamento {venda['numero']}")
        # estorna ficha (dívida) se houver
        ficha = db.execute(
            "SELECT * FROM fichas WHERE venda_id = ? AND tipo = 'lancamento'", (venda_id,)
        ).fetchone()
        if ficha and venda["cliente_id"]:
            saldo = float(db.execute("SELECT saldo_credito FROM clientes WHERE id = ?",
                                     (venda["cliente_id"],)).fetchone()[0]) - float(ficha["valor"])
            db.execute("UPDATE clientes SET saldo_credito = ?, atualizado_em = ? WHERE id = ?",
                       (round(saldo, 2), agora(), venda["cliente_id"]))
            inserir("fichas", {
                "cliente_id": venda["cliente_id"], "venda_id": venda_id, "tipo": "pagamento",
                "valor": -float(ficha["valor"]), "saldo": round(saldo, 2),
                "descricao": f"Estorno da venda {venda['numero']}",
                "usuario_id": usuario_id,
            })
        db.execute(
            """UPDATE vendas SET status = 'cancelada', cancelada_por = ?, cancelada_em = ?,
               motivo_cancelamento = ? WHERE id = ?""",
            (usuario_id, agora(), motivo, venda_id),
        )
    from .security import registrar_acao
    registrar_acao("cancelar_venda", "vendas", venda_id, f"Venda {venda['numero']} cancelada: {motivo}")
    return True


# --------------------------------------------------------------------------- FICHAS
def pagar_ficha(cliente_id, valor, usuario, descricao="Pagamento de ficha", forma="dinheiro"):
    """Registra pagamento de conta corrente do cliente."""
    valor = float(valor)
    if valor <= 0:
        raise ErroNegocio("O valor do pagamento deve ser maior que zero.")
    db = get_db()
    cliente = db.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if cliente is None:
        raise ErroNegocio("Cliente não encontrado.")
    saldo = round(float(cliente["saldo_credito"] or 0) - valor, 2)
    with transacao():
        inserir("fichas", {
            "cliente_id": cliente_id, "tipo": "pagamento", "valor": -valor, "saldo": saldo,
            "descricao": descricao, "usuario_id": valor_de(usuario, "id") if usuario else None,
        })
        db.execute("UPDATE clientes SET saldo_credito = ?, atualizado_em = ? WHERE id = ?",
                   (saldo, agora(), cliente_id))
    from .security import registrar_acao
    registrar_acao("pagar_ficha", "clientes", cliente_id, f"Pagamento de R$ {valor:,.2f} ({forma})")
    return saldo


# --------------------------------------------------------------------------- CONSULTAS
def status_estoque(estoque, minimo):
    if estoque <= 0:
        return ("zerado", "Sem estoque")
    if estoque <= (minimo or 0):
        return ("baixo", "Estoque baixo")
    return ("ok", "Normal")


def movimentacoes_recentes(produto_id, limite=40):
    db = get_db()
    return db.execute(
        """SELECT m.*, u.nome AS usuario FROM movimentacoes m
           LEFT JOIN usuarios u ON u.id = m.usuario_id
           WHERE m.produto_id = ? ORDER BY m.id DESC LIMIT ?""",
        (produto_id, limite),
    ).fetchall()
