"""Camada de acesso ao banco de dados SQLite (esquema, conexões e helpers)."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from flask import current_app, g

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nome          TEXT NOT NULL,
    login         TEXT NOT NULL UNIQUE,
    senha_hash    TEXT NOT NULL,
    perfil        TEXT NOT NULL DEFAULT 'caixa' CHECK (perfil IN ('admin','gerente','caixa')),
    ativo         INTEGER NOT NULL DEFAULT 1,
    terminal      TEXT NOT NULL DEFAULT '',
    ultimo_acesso TEXT,
    criado_em     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS auditoria (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER,
    usuario     TEXT,
    acao        TEXT NOT NULL,
    tabela      TEXT,
    registro_id INTEGER,
    detalhes    TEXT,
    ip          TEXT,
    criado_em   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS parametros (
    chave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE TABLE IF NOT EXISTS clientes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nome           TEXT NOT NULL,
    cpf            TEXT,
    rg             TEXT,
    data_nascimento TEXT,
    telefone       TEXT,
    celular        TEXT,
    email          TEXT,
    cep            TEXT,
    logradouro     TEXT,
    numero         TEXT,
    complemento    TEXT,
    bairro         TEXT,
    cidade         TEXT,
    uf             TEXT,
    observacoes    TEXT,
    limite_credito REAL NOT NULL DEFAULT 0,
    saldo_credito  REAL NOT NULL DEFAULT 0,
    pontos         INTEGER NOT NULL DEFAULT 0,
    ativo          INTEGER NOT NULL DEFAULT 1,
    criado_em      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    atualizado_em  TEXT
);
CREATE INDEX IF NOT EXISTS idx_clientes_nome ON clientes(nome);
CREATE INDEX IF NOT EXISTS idx_clientes_cpf  ON clientes(cpf);

CREATE TABLE IF NOT EXISTS fornecedores (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    razao_social   TEXT NOT NULL,
    nome_fantasia  TEXT,
    cnpj           TEXT,
    inscricao_estadual TEXT,
    telefone       TEXT,
    email          TEXT,
    contato_nome   TEXT,
    contato_fone   TEXT,
    cep            TEXT,
    logradouro     TEXT,
    numero         TEXT,
    bairro         TEXT,
    cidade         TEXT,
    uf             TEXT,
    site           TEXT,
    observacoes    TEXT,
    ativo          INTEGER NOT NULL DEFAULT 1,
    criado_em      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    atualizado_em  TEXT
);
CREATE INDEX IF NOT EXISTS idx_fornecedores_nome ON fornecedores(razao_social);

CREATE TABLE IF NOT EXISTS produtos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo              TEXT NOT NULL UNIQUE,
    ean                 TEXT,
    nome                TEXT NOT NULL,
    principio_ativo     TEXT,
    laboratorio         TEXT,
    classe_terapeutica  TEXT,
    apresentacao        TEXT,
    concentracao         TEXT,
    tarja               TEXT NOT NULL DEFAULT 'livre',
    controlado          INTEGER NOT NULL DEFAULT 0,
    receita_obrigatoria INTEGER NOT NULL DEFAULT 0,
    registro_anvisa     TEXT,
    ncm                 TEXT,
    unidade             TEXT NOT NULL DEFAULT 'UN',
    preco_custo         REAL NOT NULL DEFAULT 0,
    preco_venda         REAL NOT NULL DEFAULT 0,
    estoque             INTEGER NOT NULL DEFAULT 0,
    estoque_minimo      INTEGER NOT NULL DEFAULT 0,
    localizacao         TEXT,
    ativo               INTEGER NOT NULL DEFAULT 1,
    observacoes         TEXT,
    criado_em           TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    atualizado_em       TEXT
);
CREATE INDEX IF NOT EXISTS idx_produtos_nome    ON produtos(nome);
CREATE INDEX IF NOT EXISTS idx_produtos_ean     ON produtos(ean);
CREATE INDEX IF NOT EXISTS idx_produtos_princ   ON produtos(principio_ativo);
CREATE INDEX IF NOT EXISTS idx_produtos_lab     ON produtos(laboratorio);
CREATE INDEX IF NOT EXISTS idx_produtos_classe  ON produtos(classe_terapeutica);

CREATE TABLE IF NOT EXISTS produto_fotos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
    arquivo    TEXT NOT NULL,
    principal  INTEGER NOT NULL DEFAULT 0,
    ordem      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fotos_produto ON produto_fotos(produto_id);

CREATE TABLE IF NOT EXISTS bulas (
    produto_id        INTEGER PRIMARY KEY REFERENCES produtos(id) ON DELETE CASCADE,
    indicacoes        TEXT,
    posologia         TEXT,
    contraindicacoes  TEXT,
    efeitos_adversos  TEXT,
    advertencias      TEXT,
    interacoes        TEXT,
    gravidez          TEXT,
    sobredoagem       TEXT,
    armazenamento     TEXT,
    excipientes       TEXT,
    link_bula         TEXT,
    atualizada_em     TEXT
);

CREATE TABLE IF NOT EXISTS lotes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id    INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
    lote          TEXT,
    validade      TEXT,
    quantidade    INTEGER NOT NULL DEFAULT 0,
    preco_custo   REAL NOT NULL DEFAULT 0,
    fornecedor_id INTEGER REFERENCES fornecedores(id),
    nota_fiscal   TEXT,
    criado_em     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_lotes_produto ON lotes(produto_id);
CREATE INDEX IF NOT EXISTS idx_lotes_validade ON lotes(validade);

CREATE TABLE IF NOT EXISTS entradas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    numero          TEXT,
    fornecedor_id   INTEGER REFERENCES fornecedores(id),
    data_emissao    TEXT,
    data_recebimento TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    usuario_id      INTEGER,
    total           REAL NOT NULL DEFAULT 0,
    observacao      TEXT,
    status          TEXT NOT NULL DEFAULT 'concluida',
    criado_em       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS movimentacoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id  INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
    tipo        TEXT NOT NULL CHECK (tipo IN ('entrada','venda','ajuste','perda','devolucao','cancelamento')),
    quantidade  INTEGER NOT NULL,
    saldo_apos  INTEGER,
    tipo_ref    TEXT,
    ref_id      INTEGER,
    usuario_id  INTEGER,
    observacao  TEXT,
    criado_em   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_mov_produto ON movimentacoes(produto_id);

CREATE TABLE IF NOT EXISTS vendas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    numero           TEXT UNIQUE,
    data             TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    usuario_id       INTEGER,
    cliente_id       INTEGER REFERENCES clientes(id),
    subtotal         REAL NOT NULL DEFAULT 0,
    desconto         REAL NOT NULL DEFAULT 0,
    total            REAL NOT NULL DEFAULT 0,
    valor_pago       REAL NOT NULL DEFAULT 0,
    troco            REAL NOT NULL DEFAULT 0,
    forma_pagamento  TEXT NOT NULL DEFAULT 'dinheiro',
    status           TEXT NOT NULL DEFAULT 'concluida' CHECK (status IN ('concluida','cancelada')),
    terminal         TEXT,
    cupom_impresso   INTEGER NOT NULL DEFAULT 0,
    observacao       TEXT,
    cancelada_por    INTEGER,
    cancelada_em     TEXT,
    motivo_cancelamento TEXT,
    criado_em        TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_vendas_data    ON vendas(data);
CREATE INDEX IF NOT EXISTS idx_vendas_cliente ON vendas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_vendas_status  ON vendas(status);

CREATE TABLE IF NOT EXISTS venda_itens (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    venda_id       INTEGER NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
    produto_id     INTEGER REFERENCES produtos(id),
    nome           TEXT NOT NULL,
    codigo         TEXT,
    quantidade     INTEGER NOT NULL,
    preco_unitario REAL NOT NULL,
    desconto       REAL NOT NULL DEFAULT 0,
    subtotal       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_itens_venda    ON venda_itens(venda_id);
CREATE INDEX IF NOT EXISTS idx_itens_produto  ON venda_itens(produto_id);

CREATE TABLE IF NOT EXISTS pagamentos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    venda_id  INTEGER NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
    forma     TEXT NOT NULL,
    valor     REAL NOT NULL,
    parcelas  INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_pagamentos_venda ON pagamentos(venda_id);

CREATE TABLE IF NOT EXISTS fichas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id  INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    venda_id    INTEGER REFERENCES vendas(id),
    tipo        TEXT NOT NULL CHECK (tipo IN ('lancamento','pagamento')),
    valor       REAL NOT NULL,
    saldo       REAL NOT NULL,
    descricao   TEXT,
    vencimento  TEXT,
    pago        INTEGER NOT NULL DEFAULT 0,
    usuario_id  INTEGER,
    criado_em   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_fichas_cliente ON fichas(cliente_id);

CREATE TABLE IF NOT EXISTS backups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    arquivo     TEXT NOT NULL,
    tipo        TEXT NOT NULL DEFAULT 'completo',
    tamanho     INTEGER NOT NULL DEFAULT 0,
    hash        TEXT,
    status      TEXT NOT NULL DEFAULT 'ok',
    usuario_id  INTEGER,
    observacao  TEXT,
    criado_em   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS terminais (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nome       TEXT NOT NULL UNIQUE,
    ip         TEXT,
    usuario_id INTEGER,
    ultimo_acesso TEXT,
    criado_em  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


def get_db():
    """Retorna a conexão SQLite da requisição atual (cria sob demanda)."""
    if "db" not in g:
        path = current_app.config["DATABASE"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path, timeout=15, detect_types=sqlite3.PARSE_DECLTYPES,
                               isolation_level=None)  # transações explícitas via transacao()
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 8000")
        g.db = conn
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path=None):
    """Cria as tabelas (idempotente) e executa migrações pendentes."""
    if path is None:
        path = current_app.config["DATABASE"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    versao = conn.execute("PRAGMA user_version").fetchone()[0]
    if versao < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    conn.close()


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hoje():
    return datetime.now().strftime("%Y-%m-%d")


def executar(sql, params=()):
    """
    Executa um comando retornando o último id gerado.
    Em modo autocommit os comandos já são confirmados; quando há uma transação
    explícita aberta (transacao()), a confirmação fica a cargo do chamador.
    """
    db = get_db()
    cur = db.execute(sql, params)
    if not db.in_transaction:
        db.commit()
    return cur.lastrowid


@contextmanager
def transacao():
    """
    Gerenciador de transação (reentrante).

        with transacao():
            inserir(...)
            executar(...)
    """
    db = get_db()
    if db.in_transaction:
        yield db
        return
    db.execute("BEGIN")
    try:
        yield db
        db.execute("COMMIT")
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise


def todos(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def um(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def inserir(tabela, dados):
    cols = ", ".join(dados.keys())
    marks = ", ".join(["?"] * len(dados))
    return executar(f"INSERT INTO {tabela} ({cols}) VALUES ({marks})", tuple(dados.values()))


def atualizar(tabela, registro_id, dados):
    if not dados:
        return None
    sets = ", ".join([f"{c} = ?" for c in dados])
    executar(f"UPDATE {tabela} SET {sets} WHERE id = ?", (*dados.values(), registro_id))


def paginate(query, params=(), page=1, per_page=20):
    """Paginação simples: devolve (itens, total, páginas)."""
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM ({query}) t", params).fetchone()[0]
    page = max(1, int(page or 1))
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    offset = (page - 1) * per_page
    itens = db.execute(f"{query} LIMIT ? OFFSET ?", (*params, per_page, offset)).fetchall()
    return itens, total, page, pages
