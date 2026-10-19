"""Autenticação: login, primeiro acesso, troca de senha e logout."""
from datetime import datetime

from flask import (Blueprint, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)

from ..utils import valor_de
from ..db import get_db, um
from ..security import conferir_senha, gerar_senha, login_required, registrar_acao

bp = Blueprint("auth", __name__)

TENTATIVAS_MAX = 8


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("usuario_id"):
        return redirect(url_for("dashboard.index"))

    # primeiro acesso: nenhum usuário no sistema
    total = get_db().execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    if total == 0:
        return redirect(url_for("auth.primeiro_acesso"))

    if request.method == "POST":
        login_nome = (request.form.get("login") or "").strip()
        senha = request.form.get("senha") or ""
        tentativas = session.get("tentativas", 0)

        if tentativas >= TENTATIVAS_MAX:
            flash("Muitas tentativas inválidas. Recarregue a página e tente novamente.", "erro")
            return render_template("auth/login.html"), 429

        usuario = um("SELECT * FROM usuarios WHERE login = ? COLLATE NOCASE", (login_nome,))
        if usuario is None or not conferir_senha(usuario["senha_hash"], senha):
            session["tentativas"] = tentativas + 1
            restantes = max(0, TENTATIVAS_MAX - (tentativas + 1))
            registrar_acao("login_falhou", "usuarios", usuario["id"] if usuario else None,
                           f"Tentativa inválida para '{login_nome}'")
            flash(f"Login ou senha incorretos. Tentativas restantes: {restantes}.", "erro")
            return render_template("auth/login.html", login=login_nome), 401

        if not usuario["ativo"]:
            flash("Este usuário está desativado. Procure o administrador.", "erro")
            return render_template("auth/login.html", login=login_nome), 403

        session.clear()
        session["usuario_id"] = usuario["id"]
        session["tentativas"] = 0
        session["terminal"] = usuario["terminal"] or f"PDV-{usuario['id']:02d}"
        session["login_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        db = get_db()
        db.execute("UPDATE usuarios SET ultimo_acesso = ? WHERE id = ?",
                   (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), usuario["id"]))
        db.execute(
            """INSERT INTO terminais (nome, ip, usuario_id, ultimo_acesso)
               VALUES (?,?,?,?)
               ON CONFLICT(nome) DO UPDATE SET ip = excluded.ip, usuario_id = excluded.usuario_id,
                                               ultimo_acesso = excluded.ultimo_acesso""",
            (session["terminal"], request.remote_addr, usuario["id"],
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        db.commit()

        g.usuario = usuario
        registrar_acao("login", "usuarios", usuario["id"], f"{usuario['nome']} entrou no sistema")
        flash(f"Bem-vindo(a), {usuario['nome'].split()[0]}!", "ok")

        proximo = request.args.get("prox") or request.form.get("prox") or ""
        if proximo.startswith("/") and not proximo.startswith("//"):
            return redirect(proximo)
        return redirect(url_for("dashboard.index"))

    return render_template("auth/login.html", login=request.args.get("login", ""))


@bp.route("/primeiro-acesso", methods=["GET", "POST"])
def primeiro_acesso():
    total = get_db().execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    if total > 0 and not request.method == "POST":
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        login_nome = (request.form.get("login") or "").strip()
        senha = request.form.get("senha") or ""
        confirma = request.form.get("confirma") or ""
        if not nome or len(login_nome) < 3:
            flash("Informe o nome e um login com pelo menos 3 caracteres.", "erro")
        elif len(senha) < 6:
            flash("A senha deve ter pelo menos 6 caracteres.", "erro")
        elif senha != confirma:
            flash("As senhas não conferem.", "erro")
        else:
            db = get_db()
            existe = db.execute("SELECT 1 FROM usuarios WHERE login = ? COLLATE NOCASE", (login_nome,)).fetchone()
            if existe:
                flash("Este login já existe. Escolha outro.", "erro")
            else:
                db.execute(
                    "INSERT INTO usuarios (nome, login, senha_hash, perfil) VALUES (?,?,?, 'admin')",
                    (nome, login_nome, gerar_senha(senha)),
                )
                db.commit()
                flash("Administrador criado com sucesso! Entre com o seu login.", "ok")
                return redirect(url_for("auth.login"))

    return render_template("auth/primeiro_acesso.html")


@bp.route("/sair")
def logout():
    if session.get("usuario_id"):
        registrar_acao("logout", "usuarios", session.get("usuario_id"), "Saiu do sistema")
    session.clear()
    flash("Sessão encerrada com segurança.", "ok")
    return redirect(url_for("auth.login"))


@bp.route("/conta/senha", methods=["GET", "POST"])
@login_required()
def trocar_senha():
    if request.method == "POST":
        atual = request.form.get("atual") or ""
        nova = request.form.get("nova") or ""
        confirma = request.form.get("confirma") or ""
        if not conferir_senha(g.usuario["senha_hash"], atual):
            flash("A senha atual está incorreta.", "erro")
        elif len(nova) < 6:
            flash("A nova senha deve ter pelo menos 6 caracteres.", "erro")
        elif nova != confirma:
            flash("A confirmação não confere com a nova senha.", "erro")
        else:
            db = get_db()
            db.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (gerar_senha(nova), g.usuario["id"]))
            db.commit()
            registrar_acao("trocar_senha", "usuarios", g.usuario["id"], "Senha alterada pelo próprio usuário")
            flash("Senha alterada com sucesso!", "ok")
            return redirect(url_for("dashboard.index"))
    return render_template("auth/trocar_senha.html")


@bp.route("/api/verificar-sessao")
def verificar_sessao():
    if not session.get("usuario_id"):
        return jsonify({"expirada": True}), 401
    return jsonify({"expirada": False, "usuario": valor_de(g.get("usuario"), "nome")})
