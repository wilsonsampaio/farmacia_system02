"""FarmaciaSystem - aplicação Flask completa para gestão de farmácias."""
import os
import secrets
from datetime import datetime, timedelta

from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from . import charts, db as database
from .db import get_db, init_db, todos, um
from .security import pode as pode_acesso
from .services import ErroNegocio
from .utils import (brl, data_br, data_hora_br, dias_ate, formatar_tamanho, hora, idade,
                    mascara_cpf_cnpj)  # noqa: F401


def create_app(config_overrides=None):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    raiz = os.path.dirname(base_dir)

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        instance_relative_config=False,
    )

    data_dir = os.environ.get("FARMACIA_DADOS", os.path.join(raiz, "data"))
    upload_dir = os.path.join(data_dir, "uploads")
    backup_dir = os.path.join(data_dir, "backups")

    for pasta in (data_dir, upload_dir, os.path.join(upload_dir, "produtos"), backup_dir):
        os.makedirs(pasta, exist_ok=True)

    app.config.update(
        SECRET_KEY=_chave_secreta(data_dir),
        DATABASE=os.path.join(data_dir, "farmacia.db"),
        UPLOAD_DIR=upload_dir,
        BACKUP_DIR=backup_dir,
        BACKUP_DIR_FS=backup_dir,
        DATA_DIR=data_dir,
        MAX_CONTENT_LENGTH=64 * 1024 * 1024,  # 64 MB (uploads e arquivos de backup)
        JSON_SORT_KEYS=False,
        TEMA_PADRAO="claro",
        **(config_overrides or {}),
    )

    database.init_db(app.config["DATABASE"])

    _registrar_filtros(app)
    _registrar_erros(app)
    _registrar_contexto(app)
    _registrar_comandos_cli(app)

    from . import views as views_bp
    from .blueprints import (admin, auth, backup, clientes, dashboard, estoque,
                             fornecedores, pdv, produtos, relatorios, vendas)
    from .views import media_url

    app.jinja_env.globals["media_url"] = media_url
    app.jinja_env.globals["url_pag"] = _url_pag

    app.register_blueprint(views_bp.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(produtos.bp)
    app.register_blueprint(estoque.bp)
    app.register_blueprint(clientes.bp)
    app.register_blueprint(fornecedores.bp)
    app.register_blueprint(pdv.bp)
    app.register_blueprint(vendas.bp)
    app.register_blueprint(relatorios.bp)
    app.register_blueprint(backup.bp)
    app.register_blueprint(admin.bp)

    app.teardown_appcontext(database.close_db)

    with app.app_context():
        _primeira_execucao(app)

    return app


def _url_pag(endpoint, params=None, page=1):
    """Monta URL de páginação (substitui **params no Jinja, não suportado)."""
    args = dict(params or {})
    args["page"] = page
    return url_for(endpoint, **args)


def _chave_secreta(data_dir):
    """Chave de sessão persistida (mantém os logins mesmo após reiniciar o servidor)."""
    caminho = os.path.join(data_dir, "secret.key")
    try:
        if os.path.exists(caminho):
            with open(caminho, "r", encoding="utf-8") as fh:
                chave = fh.read().strip()
                if len(chave) >= 32:
                    return chave
        chave = secrets.token_urlsafe(48)
        with open(caminho, "w", encoding="utf-8") as fh:
            fh.write(chave)
        return chave
    except OSError:
        return secrets.token_urlsafe(48)


def _primeira_execucao(app):
    """Cria usuários iniciais e o backup automático de primeira execução."""
    qtd = get_db().execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    if qtd == 0:
        from .security import gerar_senha

        db = get_db()
        for usuario in (
            {"nome": "Administrador", "login": "admin", "senha": "admin123", "perfil": "admin"},
            {"nome": "Gerente", "login": "gerente", "senha": "gerente123", "perfil": "gerente"},
            {"nome": "Operador de Caixa", "login": "caixa", "senha": "caixa123", "perfil": "caixa"},
        ):
            db.execute(
                "INSERT INTO usuarios (nome, login, senha_hash, perfil) VALUES (?,?,?,?)",
                (usuario["nome"], usuario["login"], gerar_senha(usuario["senha"]), usuario["perfil"]),
            )
        db.commit()

    padroes = {
        "empresa_nome": "Farmácia Central",
        "empresa_fantasia": "Farmácia Central Ltda.",
        "empresa_cnpj": "00.000.000/0001-00",
        "empresa_ie": "",
        "empresa_endereco": "Rua Principal, 1000 - Centro",
        "empresa_cidade": "Sua Cidade - UF",
        "empresa_telefone": "(00) 0000-0000",
        "empresa_email": "contato@farmaciacentral.com.br",
        "empresa_crf": "CRF-UF 00000",
        "cupom_texto_rodape": "Obrigado pela preferência! Volte sempre.",
        "cupom_texto_aviso": "Documento sem valor fiscal. Lei nº 14.133/2021.",
        "estoque_alerta_dias": "60",
        "ficha_prazo_dias": "30",
        "backup_automatico": "0",
        "backup_manter": "15",
        "tema": "claro",
        "mostrar_precos_custo": "1",
    }
    db = get_db()
    alterado = False
    for chave, valor in padroes.items():
        existe = db.execute("SELECT 1 FROM parametros WHERE chave = ?", (chave,)).fetchone()
        if not existe:
            db.execute("INSERT INTO parametros (chave, valor) VALUES (?,?)", (chave, valor))
            alterado = True
    if alterado:
        db.commit()

    # Cadastros de exemplo quando o banco está vazio (dashboard já "cheio")
    try:
        from .seed import semear_se_necessario

        semear_se_necessario()
    except Exception as erro:  # noqa: BLE001
        db.rollback()
        print(f"  ! Falha ao criar dados de exemplo: {erro}")

    # Backup automático na inicialização (quando habilitado)
    try:
        ativo = db.execute("SELECT valor FROM parametros WHERE chave = 'backup_automatico'").fetchone()
        if ativo and ativo["valor"] == "1":
            from .blueprints.backup import criar_backup
            criar_backup(usuario=None, tipo="automatico", silencioso=True)
    except Exception:
        pass


def _registrar_filtros(app):
    app.jinja_env.filters["brl"] = brl
    app.jinja_env.filters["data"] = data_br
    app.jinja_env.filters["datahora"] = data_hora_br
    app.jinja_env.filters["hora"] = hora
    app.jinja_env.filters["inteiro"] = lambda v: str(int(float(v or 0)))
    app.jinja_env.filters["cpf"] = mascara_cpf_cnpj
    app.jinja_env.filters["idade"] = lambda v: (f"{idade(v)} anos" if idade(v) is not None else "-")
    app.jinja_env.filters["dias"] = dias_ate
    app.jinja_env.filters["tamanho"] = formatar_tamanho
    app.jinja_env.filters["percentual"] = lambda v: f"{float(v or 0):.1f}%".replace(".", ",")


def _registrar_erros(app):
    @app.errorhandler(ErroNegocio)
    def tratar_erro_negocio(erro):
        if request.path.startswith("/api/") or request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"erro": str(erro)}), 400
        flash(str(erro), "erro")
        destino = request.referrer or url_for("dashboard.index")
        return redirect(destino)

    @app.errorhandler(404)
    def nao_encontrado(erro):
        if request.path.startswith("/api/"):
            return jsonify({"erro": "Recurso não encontrado."}), 404
        return render_template("erro_404.html"), 404

    @app.errorhandler(403)
    def sem_permissao(erro):
        usuario = g.get("usuario") if hasattr(g, "usuario") else None
        perfil = (usuario["perfil"] if usuario and "perfil" in usuario.keys() else "?")
        return render_template("sem_permissao.html", recurso="este recurso", perfil=perfil), 403

    @app.errorhandler(500)
    def erro_interno(erro):
        try:
            get_db().rollback()
        except Exception:
            pass
        if request.path.startswith("/api/"):
            return jsonify({"erro": "Erro interno ao processar a operação."}), 500
        return render_template("erro_500.html"), 500


def _registrar_contexto(app):
    @app.before_request
    def carregar_sessao():
        g.usuario = None
        uid = session.get("usuario_id")
        if uid:
            usuario = um("SELECT * FROM usuarios WHERE id = ? AND ativo = 1", (uid,))
            if usuario:
                g.usuario = usuario
                if not session.get("terminal"):
                    session["terminal"] = f"PDV-{(usuario['terminal'] or '01')}"

    @app.context_processor
    def injetar_contexto():
        params = {}
        try:
            for linha in todos("SELECT chave, valor FROM parametros"):
                params[linha["chave"]] = linha["valor"]
        except Exception:
            pass

        alertas = {"estoque": 0, "vencimento": 0, "fichas": 0}
        try:
            dias = int(params.get("estoque_alerta_dias") or 60)
            alertas["estoque"] = get_db().execute(
                "SELECT COUNT(*) FROM produtos WHERE ativo = 1 AND estoque <= estoque_minimo"
            ).fetchone()[0]
            alertas["vencimento"] = get_db().execute(
                """SELECT COUNT(*) FROM lotes WHERE quantidade > 0 AND validade IS NOT NULL AND validade != ''
                   AND date(validade) <= date('now', ?)""",
                (f"+{dias} days",),
            ).fetchone()[0]
            alertas["fichas"] = get_db().execute(
                """SELECT COUNT(DISTINCT cliente_id) FROM fichas
                   WHERE tipo = 'lancamento' AND vencimento IS NOT NULL AND date(vencimento) < date('now')"""
            ).fetchone()[0]
        except Exception:
            pass

        return {
            "params": params,
            "empresa": {
                "nome": params.get("empresa_nome", "Farmácia"),
                "fantasia": params.get("empresa_fantasia", ""),
                "cnpj": params.get("empresa_cnpj", ""),
                "ie": params.get("empresa_ie", ""),
                "endereco": params.get("empresa_endereco", ""),
                "cidade": params.get("empresa_cidade", ""),
                "telefone": params.get("empresa_telefone", ""),
                "email": params.get("empresa_email", ""),
                "crf": params.get("empresa_crf", ""),
            },
            "alertas": alertas,
            "usuario": g.get("usuario"),
            "pode": lambda recurso: bool(g.get("usuario")) and pode_acesso(g.usuario["perfil"], recurso),
            "ano_atual": datetime.now().year,
            "hoje": datetime.now().strftime("%Y-%m-%d"),
            "flash_ativo": True,
        }


def _registrar_comandos_cli(app):
    @app.cli.command("criar-usuario")
    def criar_usuario():
        """Cria um usuário: flask --app run criar-usuario"""
        from getpass import getpass

        from .security import gerar_senha

        nome = input("Nome completo: ").strip()
        login = input("Login: ").strip()
        perfil = input("Perfil (admin/gerente/caixa) [caixa]: ").strip() or "caixa"
        senha = getpass("Senha: ")
        db = get_db()
        db.execute(
            "INSERT INTO usuarios (nome, login, senha_hash, perfil) VALUES (?,?,?,?)",
            (nome, login, gerar_senha(senha), perfil),
        )
        db.commit()
        print(f"Usuário '{login}' criado com perfil '{perfil}'.")

    @app.cli.command("backup")
    def comando_backup():
        """Gera um backup completo: flask --app run backup"""
        from .blueprints.backup import criar_backup

        info = criar_backup(usuario=None, tipo="manual", silencioso=True)
        print(f"Backup gerado: {info['arquivo']} ({info['tamanho_fmt']})")

    @app.cli.command("restaurar")
    def comando_restaurar():
        """Restaura o sistema a partir de um arquivo .zip: flask --app run restaurar caminho.zip"""
        import sys

        from .blueprints.backup import restaurar_backup

        if len(sys.argv) < 2:
            print("Informe o caminho do arquivo de backup.")
            return
        restaurar_backup(sys.argv[-1], usuario=None)
        print("Backup restaurado com sucesso.")


def obter_param(chave, padrao=""):
    try:
        row = get_db().execute("SELECT valor FROM parametros WHERE chave = ?", (chave,)).fetchone()
        return row["valor"] if row else padrao
    except Exception:
        return padrao


def definir_param(chave, valor):
    db = get_db()
    db.execute(
        "INSERT INTO parametros (chave, valor) VALUES (?,?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
        (chave, str(valor)),
    )
    db.commit()
