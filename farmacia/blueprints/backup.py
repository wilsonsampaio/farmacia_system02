"""Backup completo, restauração, exportação/importação e integração com outros sistemas."""
import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from unicodedata import normalize

from flask import (Blueprint, Response, current_app, flash, g, redirect,
                   render_template, request, send_file, url_for)

from ..db import get_db, inserir, todos, um
from ..security import admin_required, registrar_acao
from ..utils import formatar_tamanho, valor_de

bp = Blueprint("backup", __name__, url_prefix="/backup")

EXTENSOES_ZIP = (".zip",)
EXTENSOES_JSON = (".json",)

# Tabelas exportadas em JSON/CSV
TABELAS = {
    "usuarios": ["id", "nome", "login", "perfil", "ativo", "terminal", "ultimo_acesso", "criado_em"],
    "clientes": ["id", "nome", "cpf", "rg", "data_nascimento", "telefone", "celular", "email", "cep",
                 "logradouro", "numero", "complemento", "bairro", "cidade", "uf", "observacoes",
                 "limite_credito", "saldo_credito", "pontos", "ativo", "criado_em"],
    "fornecedores": ["id", "razao_social", "nome_fantasia", "cnpj", "inscricao_estadual", "telefone",
                     "email", "contato_nome", "contato_fone", "cep", "logradouro", "numero", "bairro",
                     "cidade", "uf", "site", "observacoes", "ativo", "criado_em"],
    "produtos": ["id", "codigo", "ean", "nome", "principio_ativo", "laboratorio", "classe_terapeutica",
                 "apresentacao", "concentracao", "tarja", "controlado", "receita_obrigatoria",
                 "registro_anvisa", "ncm", "unidade", "preco_custo", "preco_venda", "estoque",
                 "estoque_minimo", "localizacao", "ativo", "criado_em"],
    "bulas": ["produto_id", "indicacoes", "posologia", "contraindicacoes", "efeitos_adversos",
              "advertencias", "interacoes", "gravidez", "sobredoagem", "armazenamento", "excipientes"],
    "lotes": ["id", "produto_id", "lote", "validade", "quantidade", "preco_custo", "fornecedor_id",
              "nota_fiscal", "criado_em"],
    "vendas": ["id", "numero", "data", "usuario_id", "cliente_id", "subtotal", "desconto", "total",
               "valor_pago", "troco", "forma_pagamento", "status", "terminal", "criado_em"],
    "venda_itens": ["id", "venda_id", "produto_id", "nome", "codigo", "quantidade", "preco_unitario",
                    "desconto", "subtotal"],
    "pagamentos": ["id", "venda_id", "forma", "valor", "parcelas"],
    "movimentacoes": ["id", "produto_id", "tipo", "quantidade", "saldo_apos", "tipo_ref", "ref_id",
                      "usuario_id", "observacao", "criado_em"],
    "fichas": ["id", "cliente_id", "venda_id", "tipo", "valor", "saldo", "descricao", "vencimento",
               "pago", "usuario_id", "criado_em"],
    "entradas": ["id", "numero", "fornecedor_id", "data_emissao", "data_recebimento", "usuario_id",
                 "total", "observacao", "status", "criado_em"],
    "parametros": ["chave", "valor"],
}

# Modelos de importação: convenções de colunas usadas por sistemas do mercado
ALIAS_CAMPOS = {
    "codigo": ["codigo", "cod", "codproduto", "codinterno", "codigoexterno", "referencia", "ref",
               "cod_item", "item", "codigosistema", "sku", "codbarras"],
    "ean": ["ean", "ean13", "gtin", "codigobarras", "codigodebarras", "barcode", "barras", "codbarras",
            "codbarra", "codigobarra"],
    "nome": ["nome", "produto", "descproduto", "descricao", "descriçao", "nomedoproduto", "descricaocurta",
             "nomecomercial", "produto1", "denominacao", "descricao_venda"],
    "principio_ativo": ["principioativo", "principio", "principioativo1", "substantivoativo",
                        "composicao", "principioativo2"],
    "laboratorio": ["laboratorio", "fabricante", "empresa", "lab", "industrializador", "fabricacao"],
    "classe_terapeutica": ["classe", "classterapeutica", "grupo", "categoria", "familia",
                           "classterapeutica2", "linha"],
    "apresentacao": ["apresentacao", "apresenta", "forma", "formafarmaceutica", "embalagem", "caixa"],
    "concentracao": ["concentracao", "forca", "dosagem", "concentracao1", "dose"],
    "tarja": ["tarja", "tipotarja", "controle", "retencao"],
    "preco_custo": ["precocusto", "custo", "precomedio", "customedio", "custo2", "precofabrica",
                    "precoaquisicao", "valorcusto"],
    "preco_venda": ["precovenda", "venda", "preco", "precosugerido", "precopublico", "valorvenda",
                    "precoatual", "precomaximo"],
    "estoque": ["estoque", "saldo", "quantidade", "qtd", "qtde", "saldoestoque", "estoqueatual"],
    "estoque_minimo": ["estoqueminimo", "minimo", "pontodedecompra", "min", "estoquemin"],
    "unidade": ["unidade", "un", "umedida", "unid", "ue"],
    "localizacao": ["localizacao", "local", "endereco", "prateleira", "localdeposito"],
    "ativo": ["ativo", "situacao", "status", "flagativo"],
    "observacoes": ["observacao", "observacoes", "obs", "nota", "complemento"],
    "registro_anvisa": ["registroanvisa", "anvisa", "registro", "registroministerio"],
    "ncm": ["ncm", "codigoncm"],
    # clientes
    "nome_cliente": ["nome", "cliente", "nomedocliente", "razaosocial", "nomecliente", "pessoa",
                     "nomecompleto", "clientenome"],
    "cpf": ["cpf", "documento", "doc", "cpfcliente", "cnpj", "codcliente"],
    "rg": ["rg", "identidade", "rgie"],
    "celular": ["celular", "telefone", "fone", "cel", "whatsapp", "telefone1", "fonecelular"],
    "email": ["email", "e-mail", "mail", "correioeletronico"],
    "cidade": ["cidade", "municipio", "cid"],
    "uf": ["uf", "estado", "estado1"],
    "data_nascimento": ["datadenascimento", "nascimento", "datanascimento", "dtnascimento", "nasc"],
    "limite_credito": ["limitecredito", "limite", "limiteficha"],
    # fornecedores
    "razao_social": ["razaosocial", "razao", "fornecedor", "nomedofornecedor", "empresa", "rsocial"],
    "nome_fantasia": ["nomefantasia", "fantasia", "apelido", "fantasiadofornecedor"],
    "cnpj": ["cnpj", "cnpjcpf", "documento"],
}

MODELOS_IMPORTACAO = {
    "auto": "Detecção automática (recomendado)",
    "generico": "Sistema genérico / planilha Excel",
    "sankhya": "Sankhya ERP",
    "contax": "Contax (Gesafarm)",
    "prontifarm": "Prontifarm / Primavera",
    "universo": "Universo Sistemas",
    "tasy": "Tasy (Philips / Webjump)",
    "sifarma": "Sifarma / Fácil Farma",
    "varejo": "Varejo Fácil / Supermercados",
}


# ------------------------------------------------------------------ utilitários
def _dir_backups():
    return current_app.config["BACKUP_DIR"]


def _sha256(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(65536), b""):
            h.update(bloco)
    return h.hexdigest()


def _manifesto(arquivo, tipo, descricao=""):
    db_path = current_app.config["DATABASE"]
    return {
        "sistema": "FarmaciaSystem",
        "versao_esquema": 1,
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tipo": tipo,
        "descricao": descricao,
        "arquivo": os.path.basename(arquivo),
        "tamanho_db": os.path.getsize(db_path),
        "hash_db": _sha256(db_path),
        "usuario": valor_de(g.get("usuario"), "login") or "sistema",
        "tabelas": list(TABELAS.keys()),
    }


def criar_backup(usuario=None, tipo="manual", silencioso=False, descricao=""):
    """Gera um backup completo (.zip) com banco + fotos + manifesto e registra no histórico."""
    backup_dir = _dir_backups()
    os.makedirs(backup_dir, exist_ok=True)
    db_path = current_app.config["DATABASE"]
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    nome_arquivo = f"farmacia-backup-{tipo}-{carimbo}.zip"
    caminho = os.path.join(backup_dir, nome_arquivo)

    # cópia consistente do banco (mesmo com conexões ativas)
    fd, tmp_db = tempfile.mkstemp(suffix=".db", prefix="farmacia-copia-")
    os.close(fd)
    try:
        origem = sqlite3.connect(db_path, timeout=20)
        destino = sqlite3.connect(tmp_db)
        origem.backup(destino)
        destino.close()
        origem.close()

        manifest = _manifesto(caminho, tipo, descricao)
        manifest["hash_db"] = _sha256(tmp_db)
        manifest["tamanho_db"] = os.path.getsize(tmp_db)

        with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
            zipf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            zipf.write(tmp_db, "dados/farmacia.db")
            upload_dir = current_app.config["UPLOAD_DIR"]
            if os.path.isdir(upload_dir):
                for raiz, _dirs, arquivos in os.walk(upload_dir):
                    for arquivo in arquivos:
                        caminho_abs = os.path.join(raiz, arquivo)
                        relativo = os.path.relpath(caminho_abs, upload_dir)
                        zipf.write(caminho_abs, os.path.join("uploads", relativo))
            # exporta também um JSON legível (facilita migração para/outros sistemas)
            zipf.writestr("dados/conteudo.json", _conteudo_json())
    finally:
        if os.path.exists(tmp_db):
            os.remove(tmp_db)

    tamanho = os.path.getsize(caminho)
    hash_arquivo = _sha256(caminho)
    db = get_db()
    db.execute(
        """INSERT INTO backups (arquivo, tipo, tamanho, hash, usuario_id, observacao)
           VALUES (?,?,?,?,?,?)""",
        (nome_arquivo, tipo, tamanho, hash_arquivo,
         valor_de(usuario, "id") if usuario else None, descricao or None),
    )
    db.commit()
    _podar_backups()
    registrar_acao("backup", "backups", None, f"Backup {tipo}: {nome_arquivo} ({formatar_tamanho(tamanho)})")
    info = {"arquivo": nome_arquivo, "caminho": caminho, "tamanho": tamanho,
            "tamanho_fmt": formatar_tamanho(tamanho), "hash": hash_arquivo}
    if not silencioso:
        flash(f"Backup criado com sucesso: {nome_arquivo} ({formatar_tamanho(tamanho)}).", "ok")
    return info


def _conteudo_json():
    db = get_db()
    dados = {"sistema": "FarmaciaSystem", "gerado_em": datetime.now().isoformat(), "tabelas": {}}
    for tabela, colunas in TABELAS.items():
        try:
            linhas = db.execute(f"SELECT * FROM {tabela}").fetchall()
            dados["tabelas"][tabela] = [dict(l) for l in linhas]
        except sqlite3.Error:
            dados["tabelas"][tabela] = []
    return json.dumps(dados, ensure_ascii=False, default=str)


def _podar_backups():
    """Mantém apenas os N backups mais recentes (parametro backup_manter)."""
    try:
        manter = int((um("SELECT valor FROM parametros WHERE chave='backup_manter'") or {"valor": 15})["valor"] or 15)
    except (TypeError, ValueError, KeyError):
        manter = 15
    arquivos = todos("SELECT id, arquivo FROM backups ORDER BY id DESC")
    excedentes = arquivos[manter:]
    backup_dir = _dir_backups()
    db = get_db()
    for linha in excedentes:
        caminho = os.path.join(backup_dir, linha["arquivo"])
        if os.path.exists(caminho):
            try:
                os.remove(caminho)
            except OSError:
                pass
        db.execute("DELETE FROM backups WHERE id = ?", (linha["id"],))
    db.commit()


def _validar_banco(caminho):
    """Abre o banco do backup e verifica integridade e estrutura."""
    conn = sqlite3.connect(caminho, timeout=10)
    try:
        integridade = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if str(integridade).lower() != "ok":
            return False, f"Integridade do banco reprovada: {integridade}"
        tabelas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        obrigatorias = {"usuarios", "produtos", "vendas", "clientes", "parametros"}
        faltantes = obrigatorias - tabelas
        if faltantes:
            return False, f"O arquivo não parece ser um backup válido (faltam: {', '.join(sorted(faltantes))})."
        qtd = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        return True, f"Banco válido ({len(tabelas)} tabelas, {qtd} usuário(s))."
    except sqlite3.Error as erro:
        return False, f"Erro ao ler o banco: {erro}"
    finally:
        conn.close()


def restaurar_backup(caminho_zip, usuario=None):
    """Restaura banco e fotos a partir de um .zip gerado pelo sistema."""
    if not os.path.exists(caminho_zip):
        raise ValueError("Arquivo de backup não encontrado.")
    with tempfile.TemporaryDirectory(prefix="restaurar-") as tempdir:
        with zipfile.ZipFile(caminho_zip, "r") as zipf:
            nomes = zipf.namelist()
            nome_db = next((n for n in nomes if n.replace("\\", "/").endswith("dados/farmacia.db")), None)
            if nome_db is None:
                nome_db = next((n for n in nomes if n.lower().endswith(".db")), None)
            if nome_db is None:
                raise ValueError("O arquivo zip não contém o banco de dados (dados/farmacia.db).")
            zipf.extract(nome_db, tempdir)
            db_extraido = os.path.join(tempdir, nome_db)
            ok, mensagem = _validar_banco(db_extraido)
            if not ok:
                raise ValueError(mensagem)

            # extrai as fotos em uma pasta separada
            uploads_extraidos = os.path.join(tempdir, "uploads")
            tem_uploads = any(n.replace("\\", "/").startswith("uploads/") for n in nomes)
            if tem_uploads:
                os.makedirs(uploads_extraidos, exist_ok=True)
                for nome in nomes:
                    caminho_relativo = nome.replace("\\", "/")
                    if caminho_relativo.startswith("uploads/") and not nome.endswith("/"):
                        zipf.extract(nome, tempdir)

        # 1) backup de segurança do estado atual
        try:
            criar_backup(usuario=usuario, tipo="antes-restauracao",
                         descricao="Backup automático antes de restaurar")
        except Exception:
            pass

        # 2) fecha conexão atual e substitui os arquivos
        db_atual = g.pop("db", None)
        if db_atual is not None:
            db_atual.close()

        db_path = current_app.config["DATABASE"]
        agora = datetime.now().strftime("%Y%m%d-%H%M%S")
        for sufixo in ("", "-wal", "-shm"):
            origem = db_path + sufixo
            if os.path.exists(origem):
                shutil.move(origem, origem + f".anterior-{agora}")
        shutil.copyfile(db_extraido, db_path)

        upload_dir = current_app.config["UPLOAD_DIR"]
        if tem_uploads and os.path.isdir(uploads_extraidos):
            destino_antigo = upload_dir + f".anterior-{agora}"
            if os.path.isdir(upload_dir):
                shutil.move(upload_dir, destino_antigo)
            shutil.move(uploads_extraidos, upload_dir)
            os.makedirs(os.path.join(upload_dir, "produtos"), exist_ok=True)
            # guarda temporariamente as fotos antigas para não desperdiçar espaço
            shutil.rmtree(destino_antigo, ignore_errors=True)

    registrar_acao("restaurar_backup", "backups", None, f"Restauração a partir de {os.path.basename(caminho_zip)}")
    return True


def _codificar(texto):
    """Lê um arquivo de texto detectando a codificação mais comum do mercado."""
    if isinstance(texto, bytes):
        for codificacao in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return texto.decode(codificacao), codificacao
            except UnicodeDecodeError:
                continue
        return texto.decode("latin-1", errors="replace"), "latin-1"
    return texto, "utf-8"


def _ler_planilha(conteudo, delimitador=None):
    texto, codificacao = _codificar(conteudo)
    linhas_amostra = texto[:5000]
    if delimitador is None:
        candidatos = [";", "\t", ",", "|"]
        melhor, pontuacao = ";", 0
        primeira_linha = linhas_amostra.splitlines()[0] if linhas_amostra else ""
        for c in candidatos:
            pontuacao_local = primeira_linha.count(c)
            if pontuacao_local > pontuacao:
                melhor, pontuacao = c, pontuacao_local
        delimitador = melhor
    leitor = csv.reader(io.StringIO(texto), delimiter=delimitador)
    linhas = [l for l in leitor]
    if not linhas:
        raise ValueError("O arquivo está vazio.")
    cabecalho = [c.strip() for c in linhas[0]]
    dados = linhas[1:]
    return cabecalho, dados, delimitador, codificacao


def _normalizar(texto):
    texto = normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in texto.lower() if ch.isalnum())


def _mapear_automatico(cabecalho, campos):
    mapeamento = {}
    for idx, coluna in enumerate(cabecalho):
        alvo = _normalizar(coluna)
        if not alvo:
            continue
        for campo in campos:
            if alvo in ALIAS_CAMPOS.get(campo, [campo]) or alvo == _normalizar(campo):
                if campo not in mapeamento.values():
                    mapeamento[idx] = campo
                    break
            for alias in ALIAS_CAMPOS.get(campo, []):
                if alvo == _normalizar(alias) and campo not in mapeamento.values():
                    mapeamento[idx] = campo
                    break
    return mapeamento


def _mapear_modelo(cabecalho, campos):
    """Mapeia colunas usando as posições típicas dos sistemas do mercado."""
    mapeamento = _mapear_automatico(cabecalho, campos)
    if len(mapeamento) >= 3:
        return mapeamento
    # tenta casar pelo prefixo do cabeçalho (ex.: "Des_Produto", "Cod_Barras")
    for idx, coluna in enumerate(cabecalho):
        if idx in mapeamento:
            continue
        alvo = _normalizar(coluna)
        for campo in campos:
            base = _normalizar(campo)
            if alvo.startswith(base[:5]) and len(base) >= 4:
                mapeamento[idx] = campo
                break
    return mapeamento


# ------------------------------------------------------------------ rotas
@bp.route("/")
@admin_required
def index():
    db = get_db()
    historico = todos("""SELECT b.*, u.nome AS usuario FROM backups b
                         LEFT JOIN usuarios u ON u.id=b.usuario_id
                         ORDER BY b.id DESC LIMIT 50""")
    linhas = []
    for b in historico:
        caminho = os.path.join(_dir_backups(), b["arquivo"])
        existe = os.path.exists(caminho)
        linhas.append({**dict(b), "existe": existe,
                       "tamanho_fmt": formatar_tamanho(b["tamanho"] or 0),
                       "disponivel": existe})
    uso_db = formatar_tamanho(os.path.getsize(current_app.config["DATABASE"]))
    total_backups = sum((b["tamanho"] or 0) for b in historico if os.path.exists(os.path.join(_dir_backups(), b["arquivo"])))
    return render_template("backup/index.html", historico=linhas, uso_db=uso_db,
                           total_backups=formatar_tamanho(total_backups),
                           modelos=MODELOS_IMPORTACAO,
                           automatico=(um("SELECT valor FROM parametros WHERE chave='backup_automatico'") or {"valor": "0"})["valor"],
                           manter=(um("SELECT valor FROM parametros WHERE chave='backup_manter'") or {"valor": "15"})["valor"])


@bp.route("/criar", methods=["POST"])
@admin_required
def criar():
    descricao = (request.form.get("descricao") or "").strip()
    try:
        criar_backup(usuario=g.get("usuario"), tipo="manual", descricao=descricao)
    except Exception as erro:  # noqa: BLE001
        flash(f"Falha ao criar o backup: {erro}", "erro")
    return redirect(url_for("backup.index"))


@bp.route("/baixar/<int:backup_id>")
@admin_required
def baixar(backup_id):
    linha = um("SELECT * FROM backups WHERE id = ?", (backup_id,))
    if not linha:
        flash("Backup não encontrado.", "erro")
        return redirect(url_for("backup.index"))
    caminho = os.path.join(_dir_backups(), linha["arquivo"])
    if not os.path.exists(caminho):
        flash("O arquivo deste backup não está mais disponível no servidor.", "erro")
        return redirect(url_for("backup.index"))
    registrar_acao("baixar_backup", "backups", backup_id, linha["arquivo"])
    return send_file(caminho, as_attachment=True, download_name=linha["arquivo"])


@bp.route("/excluir/<int:backup_id>", methods=["POST"])
@admin_required
def excluir(backup_id):
    linha = um("SELECT * FROM backups WHERE id = ?", (backup_id,))
    if linha:
        caminho = os.path.join(_dir_backups(), linha["arquivo"])
        if os.path.exists(caminho):
            try:
                os.remove(caminho)
            except OSError:
                pass
        get_db().execute("DELETE FROM backups WHERE id = ?", (backup_id,))
        get_db().commit()
        registrar_acao("excluir_backup", "backups", backup_id, linha["arquivo"])
        flash("Backup removido.", "ok")
    return redirect(url_for("backup.index"))


@bp.route("/restaurar", methods=["POST"])
@admin_required
def restaurar():
    arquivo = request.files.get("arquivo")
    confirmacao = (request.form.get("confirmacao") or "").strip()
    if confirmacao.upper() != "RESTAURAR":
        flash('Digite a palavra RESTAURAR para confirmar a operação.', "erro")
        return redirect(url_for("backup.index"))

    origem = None
    if arquivo and arquivo.filename:
        ext = os.path.splitext(arquivo.filename)[1].lower()
        if ext not in EXTENSOES_ZIP:
            flash("Envie um arquivo .zip gerado pelo sistema.", "erro")
            return redirect(url_for("backup.index"))
        fd, origem = tempfile.mkstemp(suffix=".zip", prefix="restaurar-upload-")
        os.close(fd)
        arquivo.save(origem)
    else:
        backup_id = request.form.get("backup_id", type=int)
        linha = um("SELECT * FROM backups WHERE id = ?", (backup_id,)) if backup_id else None
        if not linha:
            flash("Selecione um arquivo ou um backup do histórico.", "erro")
            return redirect(url_for("backup.index"))
        origem = os.path.join(_dir_backups(), linha["arquivo"])

    try:
        restaurar_backup(origem, usuario=g.get("usuario"))
        flash("Backup restaurado com sucesso! O sistema já está usando os dados restaurados.", "ok")
    except ValueError as erro:
        flash(f"Restauração recusada: {erro}", "erro")
    except Exception as erro:  # noqa: BLE001
        flash(f"Falha na restauração: {erro}", "erro")
    finally:
        if origem and origem.startswith(tempfile.gettempdir()) and os.path.exists(origem):
            try:
                os.remove(origem)
            except OSError:
                pass
    return redirect(url_for("backup.index"))


@bp.route("/export/json")
@admin_required
def exportar_json():
    conteudo = _conteudo_json()
    registrar_acao("exportar_json", "backups", None, "Exportação completa em JSON")
    nome = f"farmacia-dados-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    return _resposta_json(conteudo, nome)


def _resposta_json(conteudo, nome):
    resposta = Response(conteudo, mimetype="application/json; charset=utf-8")
    resposta.headers["Content-Disposition"] = f"attachment; filename={nome}"
    return resposta


@bp.route("/export/csv/<tabela>")
@admin_required
def exportar_csv(tabela):
    if tabela not in TABELAS:
        flash("Tabela não suportada para exportação.", "erro")
        return redirect(url_for("backup.index"))
    colunas = TABELAS[tabela]
    linhas = todos(f"SELECT * FROM {tabela}")
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";")
    escritor.writerow(colunas)
    for linha in linhas:
        escritor.writerow([linha[c] if c in linha.keys() else "" for c in colunas])
    registro = "\ufeff" + saida.getvalue()
    registrar_acao("exportar_csv", "backups", None, f"Tabela {tabela} ({len(linhas)} linhas)")
    resposta = Response(registro, mimetype="text/csv; charset=utf-8")
    resposta.headers["Content-Disposition"] = f"attachment; filename=export_{tabela}.csv"
    return resposta


@bp.route("/export/todos-csv")
@admin_required
def exportar_todos_csv():
    """Gera um .zip com todas as tabelas em CSV (compatível com Excel e outros sistemas)."""
    fd, temp_zip = tempfile.mkstemp(suffix=".zip", prefix="csv-export-")
    os.close(fd)
    with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for tabela, colunas in TABELAS.items():
            linhas = todos(f"SELECT * FROM {tabela}")
            saida = io.StringIO()
            escritor = csv.writer(saida, delimiter=";")
            escritor.writerow(colunas)
            for linha in linhas:
                escritor.writerow([linha[c] if c in linha.keys() else "" for c in colunas])
            zipf.writestr(f"csv/{tabela}.csv", "\ufeff" + saida.getvalue())
        zipf.writestr("README.txt",
                      "Exportação gerada pelo FarmaciaSystem\n"
                      f"Data: {datetime.now():%d/%m/%Y %H:%M}\n"
                      "Codificação: UTF-8 | Separador: ponto e vírgula (;)\n")
    registrar_acao("exportar_zip_csv", "backups", None, "Exportação de todas as tabelas em CSV")
    nome = f"farmacia-csv-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return send_file(temp_zip, as_attachment=True, download_name=nome)


@bp.route("/importar", methods=["GET", "POST"])
@admin_required
def importar():
    """Etapa 1: envio do arquivo (CSV de outro sistema, Excel salvo como CSV ou JSON)."""
    if request.method == "GET":
        return render_template("backup/importacao.html", modelos=MODELOS_IMPORTACAO,
                               tabelas=[("produtos", "Produtos"), ("clientes", "Clientes"),
                                        ("fornecedores", "Fornecedores")], etapa=1)
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        flash("Selecione um arquivo para importar.", "erro")
        return redirect(url_for("backup.importar"))
    ext = os.path.splitext(arquivo.filename)[1].lower()
    if ext not in (".csv", ".txt", ".json"):
        flash("Formatos aceitos: .csv, .txt e .json (Excel: Salvar como CSV).", "erro")
        return redirect(url_for("backup.importar"))
    conteudo = arquivo.read()
    destino = os.path.join(tempfile.gettempdir(), f"import-{datetime.now().strftime('%H%M%S')}{ext}")
    with open(destino, "wb") as fh:
        fh.write(conteudo)

    if ext == ".json":
        try:
            dados = json.loads(conteudo.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            flash("JSON inválido ou ilegível.", "erro")
            return redirect(url_for("backup.importar"))
        if not dados.get("tabelas"):
            flash("O JSON não contém a estrutura de tabelas do sistema.", "erro")
            return redirect(url_for("backup.importar"))
        return render_template("backup/importacao.html", modelos=MODELOS_IMPORTACAO, etapa=3,
                               dados=dados, tabelas_json=list(dados.get("tabelas", {}).keys()))

    try:
        cabecalho, linhas, delimitador, codificacao = _ler_planilha(conteudo)
    except ValueError as erro:
        flash(str(erro), "erro")
        return redirect(url_for("backup.importar"))
    except Exception as erro:  # noqa: BLE001
        flash(f"Não foi possível ler o arquivo: {erro}", "erro")
        return redirect(url_for("backup.importar"))

    tabela = request.form.get("tabela") or "produtos"
    modelo = request.form.get("modelo") or "auto"
    campos = list(_campos_disponiveis(tabela))
    if modelo == "auto":
        mapeamento = _mapear_automatico(cabecalho, campos)
    else:
        mapeamento = _mapear_modelo(cabecalho, campos)
    # guarda o arquivo para a próxima etapa
    caminho_cache = os.path.join(tempfile.gettempdir(), "farmacia-import-atual.json")
    with open(caminho_cache, "w", encoding="utf-8") as fh:
        json.dump({"destino": destino, "tabela": tabela, "modelo": modelo,
                   "delimitador": delimitador, "codificacao": codificacao}, fh)
    # 'colunas' e não 'cabecalho': o template importa a macro homônima de macros.html
    return render_template("backup/importacao.html", modelos=MODELOS_IMPORTACAO, etapa=2,
                           tabela=tabela, modelo=modelo, colunas=list(enumerate(cabecalho)),
                           amostra=linhas[:5], total_linhas=len(linhas),
                           mapeamento={int(k): v for k, v in mapeamento.items()},
                           campos=campos, delimitador=delimitador, codificacao=codificacao,
                           destino=destino, nome_arquivo=arquivo.filename)


def _campos_disponiveis(tabela):
    if tabela == "produtos":
        return ["codigo", "nome", "ean", "principio_ativo", "laboratorio", "classe_terapeutica",
                "apresentacao", "concentracao", "tarja", "preco_custo", "preco_venda", "estoque",
                "estoque_minimo", "unidade", "localizacao", "registro_anvisa", "ncm", "ativo",
                "observacoes"]
    if tabela == "clientes":
        return ["nome", "cpf", "rg", "celular", "email", "cidade", "uf", "data_nascimento",
                "limite_credito", "telefone"]
    return ["razao_social", "nome_fantasia", "cnpj", "telefone", "email", "cidade", "uf",
            "contato_nome", "inscricao_estadual"]


@bp.route("/importar/aplicar", methods=["POST"])
@admin_required
def importar_aplicar():
    """Etapa 2: aplicação do mapeamento com opções de criação/atualização."""
    destino = request.form.get("destino")
    tabela = request.form.get("tabela") or "produtos"
    acao = request.form.get("acao") or "criar"
    if not destino or not os.path.exists(destino):
        flash("O arquivo importado expirou. Envie novamente.", "erro")
        return redirect(url_for("backup.importar"))
    with open(destino, "rb") as fh:
        conteudo = fh.read()
    try:
        cabecalho, linhas, _delim, _cod = _ler_planilha(conteudo)
    except Exception as erro:  # noqa: BLE001
        flash(f"Erro ao reler o arquivo: {erro}", "erro")
        return redirect(url_for("backup.importar"))

    colunas_form = request.form.getlist("coluna")
    campos_form = request.form.getlist("campo")
    mapeamento = {}
    for idx_str, campo in zip(colunas_form, campos_form):
        if campo:
            mapeamento[int(idx_str)] = campo

    criados, atualizados, ignorados, erros = 0, 0, 0, []
    for num_linha, linha in enumerate(linhas, start=2):
        valores = {}
        for idx, campo in mapeamento.items():
            valores[campo] = linha[idx].strip() if idx < len(linha) else ""
        if not any(valores.values()):
            ignorados += 1
            continue
        try:
            resultado = _importar_linha(tabela, valores, acao)
            if resultado == "criado":
                criados += 1
            elif resultado == "atualizado":
                atualizados += 1
            else:
                ignorados += 1
        except Exception as erro:  # noqa: BLE001
            erros.append(f"Linha {num_linha}: {erro}")
            if len(erros) >= 40:
                break

    registrar_acao("importar_csv", "backups", None,
                   f"{tabela}: {criados} criados, {atualizados} atualizados, "
                   f"{ignorados} ignorados, {len(erros)} erros")
    flash(f"Importação concluída: {criados} criado(s), {atualizados} atualizado(s), "
          f"{ignorados} ignorado(s), {len(erros)} erro(s).", "ok" if not erros else "aviso")
    return render_template("backup/importacao.html", modelos=MODELOS_IMPORTACAO, etapa=4,
                           criados=criados, atualizados=atualizados, ignorados=ignorados,
                           erros=erros, tabela=tabela)


def _numero_import(texto):
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


def _importar_linha(tabela, valores, acao):
    from ..utils import cnpj_valido, cpf_valido, data_iso, digitos, mascara_cnpj, mascara_cpf

    db = get_db()
    if tabela == "produtos":
        codigo = (valores.get("codigo") or "").strip()
        nome = (valores.get("nome") or "").strip()
        if not nome:
            raise ValueError("linha sem nome do produto")
        if not codigo:
            codigo = f"IMP{digestor(nome)[:10]}"
        existente = um("SELECT id FROM produtos WHERE codigo = ? COLLATE NOCASE", (codigo,))
        dados = {
            "codigo": codigo,
            "nome": nome,
            "ean": digitos(valores.get("ean")) or None,
            "principio_ativo": (valores.get("principio_ativo") or "").strip() or None,
            "laboratorio": (valores.get("laboratorio") or "").strip() or None,
            "classe_terapeutica": (valores.get("classe_terapeutica") or "").strip() or None,
            "apresentacao": (valores.get("apresentacao") or "").strip() or None,
            "concentracao": (valores.get("concentracao") or "").strip() or None,
            "tarja": (valores.get("tarja") or "livre").strip().lower() or "livre",
            "preco_custo": round(_numero_import(valores.get("preco_custo")), 2),
            "preco_venda": round(_numero_import(valores.get("preco_venda")), 2),
            "estoque_minimo": int(_numero_import(valores.get("estoque_minimo"))),
            "unidade": (valores.get("unidade") or "UN").strip().upper() or "UN",
            "localizacao": (valores.get("localizacao") or "").strip() or None,
            "registro_anvisa": (valores.get("registro_anvisa") or "").strip() or None,
            "ncm": (valores.get("ncm") or "").strip() or None,
            "observacoes": (valores.get("observacoes") or "").strip() or None,
            "ativo": 1 if str(valores.get("ativo", "1")).strip().lower() in ("", "1", "sim", "s", "ativo", "true") else 0,
            "atualizado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if existente and acao == "ignorar":
            return "ignorado"
        if existente:
            dados.pop("atualizado_em")
            dados["atualizado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.execute(
                f"""UPDATE produtos SET {', '.join(f'{c} = ?' for c in dados if c != 'codigo')} 
                    WHERE id = ?""", (*[v for k, v in dados.items() if k != "codigo"], existente["id"]))
            db.commit()
            estoque = _numero_import(valores.get("estoque"))
            if estoque > 0:
                from ..services import ajustar_estoque
                ajustar_estoque(existente["id"], int(estoque), "Importação de dados de outro sistema")
            return "atualizado"
        if acao == "atualizar":
            return "ignorado"
        estoque_inicial = int(_numero_import(valores.get("estoque")))
        dados_sem_estoque = {k: v for k, v in dados.items() if k not in ("atualizado_em",)}
        produto_id = inserir("produtos", dados_sem_estoque)
        if estoque_inicial > 0:
            from ..services import entrada_estoque
            entrada_estoque(produto_id, estoque_inicial, lote="IMPORTACAO",
                            custo=dados["preco_custo"], observacao="Importação de outro sistema")
        return "criado"

    if tabela == "clientes":
        nome = (valores.get("nome") or valores.get("nome_cliente") or "").strip()
        if not nome:
            raise ValueError("linha sem nome do cliente")
        doc = digitos(valores.get("cpf"))
        cpf_formatado = None
        if doc:
            if len(doc) == 11 and cpf_valido(doc):
                cpf_formatado = mascara_cpf(doc)
            elif len(doc) == 14:
                cpf_formatado = None  # CNPJ não cabe no campo CPF
        existente = None
        if cpf_formatado:
            existente = um("SELECT id FROM clientes WHERE cpf = ?", (cpf_formatado,))
        if existente is None:
            existente = um("SELECT id FROM clientes WHERE nome = ? COLLATE NOCASE", (nome,))
        dados = {
            "nome": nome,
            "cpf": cpf_formatado,
            "rg": (valores.get("rg") or "").strip() or None,
            "celular": (valores.get("celular") or valores.get("telefone") or "").strip() or None,
            "telefone": (valores.get("telefone") or "").strip() or None,
            "email": (valores.get("email") or "").strip() or None,
            "cidade": (valores.get("cidade") or "").strip() or None,
            "uf": (valores.get("uf") or "").strip().upper()[:2] or None,
            "data_nascimento": data_iso(valores.get("data_nascimento")),
            "limite_credito": round(_numero_import(valores.get("limite_credito")), 2),
            "atualizado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if existente:
            if acao == "ignorar":
                return "ignorado"
            cols = [c for c in dados if c != "nome"]
            db.execute(f"UPDATE clientes SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?",
                       (*[dados[c] for c in cols], existente["id"]))
            db.commit()
            return "atualizado"
        if acao == "atualizar":
            return "ignorado"
        inserir("clientes", {k: v for k, v in dados.items() if k != "atualizado_em"})
        return "criado"

    # fornecedores
    razao = (valores.get("razao_social") or valores.get("nome") or "").strip()
    if not razao:
        raise ValueError("linha sem razão social")
    doc = digitos(valores.get("cnpj"))
    cnpj_formatado = mascara_cnpj(doc) if len(doc) == 14 and cnpj_valido(doc) else None
    existente = um("SELECT id FROM fornecedores WHERE cnpj = ?", (cnpj_formatado,)) if cnpj_formatado else None
    dados = {
        "razao_social": razao,
        "nome_fantasia": (valores.get("nome_fantasia") or "").strip() or None,
        "cnpj": cnpj_formatado,
        "inscricao_estadual": (valores.get("inscricao_estadual") or "").strip() or None,
        "telefone": (valores.get("telefone") or "").strip() or None,
        "email": (valores.get("email") or "").strip() or None,
        "contato_nome": (valores.get("contato_nome") or "").strip() or None,
        "cidade": (valores.get("cidade") or "").strip() or None,
        "uf": (valores.get("uf") or "").strip().upper()[:2] or None,
        "atualizado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if existente:
        if acao == "ignorar":
            return "ignorado"
        cols = [c for c in dados if c != "razao_social"]
        db.execute(f"UPDATE fornecedores SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?",
                   (*[dados[c] for c in cols], existente["id"]))
        db.commit()
        return "atualizado"
    if acao == "atualizar":
        return "ignorado"
    inserir("fornecedores", {k: v for k, v in dados.items() if k != "atualizado_em"})
    return "criado"


def digestor(texto):
    return hashlib.md5(str(texto).encode("utf-8")).hexdigest().upper()


@bp.route("/importar/json", methods=["POST"])
@admin_required
def importar_json():
    """Restaura dados a partir de um arquivo JSON gerado por este ou outro sistema."""
    arquivo = request.files.get("arquivo")
    confirmacao = (request.form.get("confirmacao") or "").strip().upper()
    if confirmacao != "RESTAURAR":
        flash('Digite RESTAURAR para confirmar a importação do JSON (substitui os dados atuais).', "erro")
        return redirect(url_for("backup.importar"))
    if not arquivo or not arquivo.filename.lower().endswith(".json"):
        flash("Selecione um arquivo .json.", "erro")
        return redirect(url_for("backup.importar"))
    try:
        dados = json.loads(arquivo.read().decode("utf-8-sig"))
        tabelas = dados.get("tabelas") or dados
    except (ValueError, UnicodeDecodeError):
        flash("JSON inválido.", "erro")
        return redirect(url_for("backup.importar"))

    # backup de segurança antes de sobrescrever
    try:
        criar_backup(usuario=g.get("usuario"), tipo="antes-importar-json")
    except Exception:
        pass

    from ..db import init_db

    # snapshot dos usuários: se o JSON vier sem eles, o admin não pode ficar trancado fora
    usuarios_antigos = todos("SELECT * FROM usuarios")
    db_antigo = g.pop("db", None)
    if db_antigo is not None:
        db_antigo.close()
    db_path = current_app.config["DATABASE"]
    for sufixo in ("", "-wal", "-shm"):
        if os.path.exists(db_path + sufixo):
            os.remove(db_path + sufixo)
    init_db(db_path)
    db = get_db()
    inseridos = 0
    ordem = ["parametros", "usuarios", "clientes", "fornecedores", "produtos", "bulas", "lotes",
             "entradas", "vendas", "venda_itens", "pagamentos", "movimentacoes", "fichas"]
    for tabela in ordem:
        linhas = tabelas.get(tabela) or []
        if not linhas:
            continue
        colunas_disponiveis = {c["name"] for c in db.execute(f"PRAGMA table_info({tabela})").fetchall()}
        for linha in linhas:
            dados_linha = {k: v for k, v in linha.items() if k in colunas_disponiveis}
            if not dados_linha:
                continue
            cols = ", ".join(dados_linha)
            marks = ", ".join(["?"] * len(dados_linha))
            try:
                db.execute(f"INSERT INTO {tabela} ({cols}) VALUES ({marks})", tuple(dados_linha.values()))
                inseridos += 1
            except sqlite3.Error:
                continue
    db.commit()
    # preserva o acesso: se o JSON não trouxe usuários, recoloca os atuais
    if usuarios_antigos and not um("SELECT 1 FROM usuarios LIMIT 1"):
        colunas_u = list(usuarios_antigos[0].keys())
        for u in usuarios_antigos:
            db.execute(
                f"INSERT INTO usuarios ({', '.join(colunas_u)}) VALUES ({', '.join('?' * len(colunas_u))})",
                tuple(u[c] for c in colunas_u))
        db.commit()
    registrar_acao("importar_json", "backups", None, f"Importação de JSON com {inseridos} registros")
    flash(f"JSON importado com sucesso: {inseridos} registros gravados.", "ok")
    return redirect(url_for("backup.index"))


@bp.route("/config", methods=["POST"])
@admin_required
def configurar():
    automatico = "1" if request.form.get("automatico") else "0"
    manter = request.form.get("manter") or "15"
    try:
        manter = max(1, min(500, int(manter)))
    except ValueError:
        manter = 15
    db = get_db()
    for chave, valor in (("backup_automatico", automatico), ("backup_manter", str(manter))):
        db.execute("INSERT INTO parametros (chave, valor) VALUES (?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                   (chave, valor))
    db.commit()
    registrar_acao("config_backup", "parametros", None, f"Automático={automatico}, manter={manter}")
    flash("Configurações de backup atualizadas.", "ok")
    return redirect(url_for("backup.index"))


@bp.route("/agendar", methods=["POST"])
@admin_required
def agendar():
    """Cria um backup imediato e informa a próxima execução automática."""
    try:
        info = criar_backup(usuario=g.get("usuario"), tipo="programado")
        flash(f"Backup programado gerado: {info['arquivo']} ({info['tamanho_fmt']}).", "ok")
    except Exception as erro:  # noqa: BLE001
        flash(f"Erro ao gerar backup: {erro}", "erro")
    return redirect(url_for("backup.index"))


@bp.route("/verificar")
@admin_required
def verificar():
    """Verifica a integridade do banco de dados atual e dos backups do histórico."""
    db = get_db()
    integridade = db.execute("PRAGMA integrity_check").fetchone()[0]
    qtd = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
           ("produtos", "clientes", "fornecedores", "vendas", "venda_itens", "usuarios")}
    resultados = []
    for linha in todos("SELECT * FROM backups ORDER BY id DESC LIMIT 20"):
        caminho = os.path.join(_dir_backups(), linha["arquivo"])
        if not os.path.exists(caminho):
            resultados.append((linha["arquivo"], "ausente", "Arquivo não encontrado no servidor."))
            continue
        hash_atual = _sha256(caminho)
        confere = (hash_atual == linha["hash"]) if linha["hash"] else None
        resultados.append((linha["arquivo"], "ok" if confere else "divergente",
                           "Integridade confirmada (SHA-256)." if confere else
                           "Hash divergente do registrado — arquivo possivelmente alterado."))
    registrar_acao("verificar_backup", "backups", None, f"Integridade: {integridade}")
    flash(f"Integridade do banco: {integridade}. Registros: " +
          ", ".join(f"{k}={v}" for k, v in qtd.items()) + ".", "ok" if str(integridade).lower() == "ok" else "erro")
    return render_template("backup/verificacao.html", integridade=integridade, qtd=qtd, resultados=resultados)
