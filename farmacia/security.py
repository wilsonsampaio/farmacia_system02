"""Autenticação, permissões e auditoria do sistema."""
import functools

from flask import g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, inserir, todos, um

# Recursos x perfis que podem acessá-los
PERMISSOES = {
    "admin": {"*"},
    "gerente": {
        "dashboard", "pdv", "vendas", "produtos", "estoque", "clientes",
        "fornecedores", "relatorios", "fichas", "consultas",
    },
    "caixa": {
        "dashboard", "pdv", "vendas", "clientes", "consultas", "produtos.consultar", "fichas",
    },
}


def pode(perfil, recurso):
    permissoes = PERMISSOES.get(perfil, set())
    if "*" in permissoes:
        return True
    if recurso in permissoes:
        return True
    # "produtos.consultar" é coberto por "produtos"
    base = recurso.split(".")[0]
    return base in permissoes


def gerar_senha(senha):
    return generate_password_hash(senha)


def conferir_senha(hash_senha, senha):
    return check_password_hash(hash_senha, senha)


def usuario_atual():
    return g.get("usuario")


def login_required(recurso=None):
    def decorador(funcao):
        @functools.wraps(funcao)
        def interna(*args, **kwargs):
            uid = session.get("usuario_id")
            if not uid:
                if request.path.startswith("/api/"):
                    return {"erro": "Sessão expirada. Entre novamente."}, 401
                return redirect(url_for("auth.login", prox=request.full_path.rstrip("?")))
            usuario = um("SELECT * FROM usuarios WHERE id = ? AND ativo = 1", (uid,))
            if usuario is None:
                session.clear()
                return redirect(url_for("auth.login"))
            g.usuario = usuario
            if recurso and not pode(usuario["perfil"], recurso):
                return render_template(
                    "sem_permissao.html",
                    recurso=recurso,
                    perfil=usuario["perfil"],
                ), 403
            return funcao(*args, **kwargs)

        return interna

    return decorador


def admin_required(funcao):
    return login_required("*")(funcao)


def registrar_acao(acao, tabela=None, registro_id=None, detalhes=""):
    """Grava uma linha na auditoria (nunca derruba a requisição)."""
    try:
        from .utils import valor_de

        usuario = g.get("usuario")
        inserir(
            "auditoria",
            {
                "usuario_id": valor_de(usuario, "id"),
                "usuario": valor_de(usuario, "login") or "sistema",
                "acao": acao,
                "tabela": tabela,
                "registro_id": registro_id,
                "detalhes": detalhes,
                "ip": request.remote_addr if request else None,
            },
        )
    except Exception:
        pass


def limpar_auditoria(conservar=50000):
    try:
        db = get_db()
        db.execute(
            """DELETE FROM auditoria WHERE id NOT IN
               (SELECT id FROM auditoria ORDER BY id DESC LIMIT ?)""",
            (conservar,),
        )
        db.commit()
    except Exception:
        pass


def historico_usuario(usuario_id, limite=50):
    return todos(
        "SELECT * FROM auditoria WHERE usuario_id = ? ORDER BY id DESC LIMIT ?",
        (usuario_id, limite),
    )
