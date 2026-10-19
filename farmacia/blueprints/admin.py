"""Administração: usuários, parâmetros da empresa, terminais e auditoria."""
from flask import (Blueprint, flash, g, redirect, render_template, request, url_for)

from ..db import agora, get_db, paginate, todos, um
from ..security import admin_required, gerar_senha, login_required, registrar_acao
from ..utils import PERFIS, brl, salvar_foto

bp = Blueprint("admin", __name__, url_prefix="/admin")


# ------------------------------------------------------------------ usuários
@bp.route("/usuarios")
@admin_required
def usuarios():
    itens = todos("""SELECT u.*, (SELECT COUNT(*) FROM vendas v WHERE v.usuario_id=u.id AND v.status='concluida') AS vendas,
                            (SELECT COALESCE(SUM(v.total),0) FROM vendas v WHERE v.usuario_id=u.id AND v.status='concluida') AS faturamento
                     FROM usuarios u ORDER BY u.nome""")
    return render_template("admin/usuarios.html", itens=itens, perfis=PERFIS)


@bp.route("/usuarios/novo", methods=["GET", "POST"])
@admin_required
def usuario_novo():
    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        login_nome = (request.form.get("login") or "").strip()
        senha = request.form.get("senha") or ""
        perfil = request.form.get("perfil") or "caixa"
        terminal = (request.form.get("terminal") or "").strip()
        if len(nome) < 3 or len(login_nome) < 3:
            flash("Informe nome e um login com pelo menos 3 caracteres.", "erro")
            return render_template("admin/usuario_form.html", alvo=None, perfis=PERFIS), 400
        if len(senha) < 6:
            flash("A senha deve ter pelo menos 6 caracteres.", "erro")
            return render_template("admin/usuario_form.html", alvo=None, perfis=PERFIS), 400
        if um("SELECT id FROM usuarios WHERE login = ? COLLATE NOCASE", (login_nome,)):
            flash("Este login já está em uso.", "erro")
            return render_template("admin/usuario_form.html", alvo=None, perfis=PERFIS), 400
        if perfil not in ("admin", "gerente", "caixa"):
            perfil = "caixa"
        db = get_db()
        cur = db.execute(
            "INSERT INTO usuarios (nome, login, senha_hash, perfil, terminal) VALUES (?,?,?,?,?)",
            (nome, login_nome, gerar_senha(senha), perfil, terminal))
        db.commit()
        registrar_acao("criar_usuario", "usuarios", cur.lastrowid, f"{nome} ({perfil})")
        flash(f"Usuário '{nome}' criado com perfil '{perfil}'.", "ok")
        return redirect(url_for("admin.usuarios"))
    return render_template("admin/usuario_form.html", alvo=None, perfis=PERFIS)


@bp.route("/usuarios/<int:usuario_id>/editar", methods=["GET", "POST"])
@admin_required
def usuario_editar(usuario_id):
    usuario = um("SELECT * FROM usuarios WHERE id = ?", (usuario_id,))
    if not usuario:
        flash("Usuário não encontrado.", "erro")
        return redirect(url_for("admin.usuarios"))
    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        login_nome = (request.form.get("login") or "").strip()
        perfil = request.form.get("perfil") or usuario["perfil"]
        terminal = (request.form.get("terminal") or "").strip()
        ativo = 1 if request.form.get("ativo") else 0
        if len(nome) < 3 or len(login_nome) < 3:
            flash("Nome e login precisam ter pelo menos 3 caracteres.", "erro")
            return render_template("admin/usuario_form.html", alvo=usuario, perfis=PERFIS), 400
        if um("SELECT id FROM usuarios WHERE login = ? COLLATE NOCASE AND id != ?", (login_nome, usuario_id)):
            flash("Este login já está em uso por outro usuário.", "erro")
            return render_template("admin/usuario_form.html", alvo=usuario, perfis=PERFIS), 400
        if usuario_id == g.usuario["id"] and (perfil != "admin" or not ativo):
            flash("Você não pode alterar o próprio perfil ou se desativar.", "erro")
            return render_template("admin/usuario_form.html", alvo=usuario, perfis=PERFIS), 400
        db = get_db()
        db.execute("""UPDATE usuarios SET nome=?, login=?, perfil=?, terminal=?
                      WHERE id=?""", (nome, login_nome, perfil, terminal, usuario_id))
        db.execute("UPDATE usuarios SET ativo=? WHERE id=?", (ativo, usuario_id))
        db.commit()
        registrar_acao("editar_usuario", "usuarios", usuario_id, f"{nome} ({perfil}) ativo={ativo}")
        flash("Usuário atualizado!", "ok")
        return redirect(url_for("admin.usuarios"))
    return render_template("admin/usuario_form.html", alvo=usuario, perfis=PERFIS)


@bp.route("/usuarios/<int:usuario_id>/senha", methods=["POST"])
@admin_required
def usuario_senha(usuario_id):
    usuario = um("SELECT * FROM usuarios WHERE id = ?", (usuario_id,))
    if not usuario:
        flash("Usuário não encontrado.", "erro")
        return redirect(url_for("admin.usuarios"))
    senha = request.form.get("senha") or ""
    if len(senha) < 6:
        flash("A nova senha deve ter pelo menos 6 caracteres.", "erro")
        return redirect(url_for("admin.usuario_editar", usuario_id=usuario_id))
    db = get_db()
    db.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (gerar_senha(senha), usuario_id))
    db.commit()
    registrar_acao("resetar_senha", "usuarios", usuario_id, f"Senha redefinida para {usuario['login']}")
    flash(f"Senha de '{usuario['nome']}' redefinida.", "ok")
    return redirect(url_for("admin.usuario_editar", usuario_id=usuario_id))


@bp.route("/usuarios/<int:usuario_id>/excluir", methods=["POST"])
@admin_required
def usuario_excluir(usuario_id):
    usuario = um("SELECT * FROM usuarios WHERE id = ?", (usuario_id,))
    if not usuario:
        flash("Usuário não encontrado.", "erro")
        return redirect(url_for("admin.usuarios"))
    if usuario_id == g.usuario["id"]:
        flash("Você não pode excluir o próprio usuário.", "erro")
        return redirect(url_for("admin.usuarios"))
    tem_vendas = um("SELECT 1 FROM vendas WHERE usuario_id = ? LIMIT 1", (usuario_id,))
    db = get_db()
    if tem_vendas:
        db.execute("UPDATE usuarios SET ativo = 0 WHERE id = ?", (usuario_id,))
        flash("O usuário possui histórico de vendas e foi apenas desativado.", "ok")
    else:
        db.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
        flash("Usuário excluído.", "ok")
    db.commit()
    registrar_acao("excluir_usuario", "usuarios", usuario_id, usuario["nome"])
    return redirect(url_for("admin.usuarios"))


# ------------------------------------------------------------------ parâmetros
PARAMETROS_TEXTO = {
    "empresa_nome": "Nome da farmácia",
    "empresa_fantasia": "Razão social / nome fantasia",
    "empresa_cnpj": "CNPJ",
    "empresa_ie": "Inscrição estadual",
    "empresa_endereco": "Endereço",
    "empresa_cidade": "Cidade - UF",
    "empresa_telefone": "Telefone",
    "empresa_email": "E-mail",
    "empresa_crf": "Registro no CRF",
    "cupom_texto_rodape": "Texto do rodapé do cupom",
    "cupom_texto_aviso": "Aviso no rodapé do cupom",
    "estoque_alerta_dias": "Alerta de vencimento (dias)",
    "ficha_prazo_dias": "Vencimento padrão da ficha (dias)",
    "meta_diaria": "Meta de vendas por dia (R$)",
    "backup_manter": "Backups mantidos no servidor",
    "tema": "Tema padrão da interface",
}


@bp.route("/empresa", methods=["GET", "POST"])
@admin_required
def empresa():
    db = get_db()
    if request.method == "POST":
        for chave in PARAMETROS_TEXTO:
            if chave in request.form:
                valor = (request.form.get(chave) or "").strip()
                db.execute("""INSERT INTO parametros (chave, valor) VALUES (?,?)
                              ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor""", (chave, valor))
        arquivo = request.files.get("logo")
        if arquivo and arquivo.filename:
            nome = salvar_foto(arquivo, subpasta="empresa")
            if nome:
                db.execute("""INSERT INTO parametros (chave, valor) VALUES ('empresa_logo',?)
                              ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor""", (nome,))
            else:
                flash("O arquivo de logo precisa ser uma imagem (JPG, PNG ou WEBP).", "erro")
        if request.form.get("remover_logo"):
            atual = db.execute("SELECT valor FROM parametros WHERE chave='empresa_logo'").fetchone()
            if atual:
                from ..utils import apagar_foto
                apagar_foto(atual["valor"], subpasta="empresa")
                db.execute("DELETE FROM parametros WHERE chave='empresa_logo'")
        db.commit()
        registrar_acao("editar_empresa", "parametros", None, "Dados da empresa atualizados")
        flash("Dados da empresa salvos!", "ok")
        return redirect(url_for("admin.empresa"))
    params = {linha["chave"]: linha["valor"] for linha in todos("SELECT chave, valor FROM parametros")}
    return render_template("admin/empresa.html", params=params, textos=PARAMETROS_TEXTO,
                           brl=brl)


@bp.route("/parametros", methods=["POST"])
@admin_required
def parametros():
    db = get_db()
    for chave, valor in request.form.items():
        if chave.startswith("p_"):
            db.execute("""INSERT INTO parametros (chave, valor) VALUES (?,?)
                          ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor""",
                       (chave[2:], str(valor)))
    db.commit()
    registrar_acao("editar_parametros", "parametros", None, ", ".join(k[2:] for k in request.form if k.startswith("p_")))
    flash("Configurações salvas!", "ok")
    return redirect(request.referrer or url_for("admin.empresa"))


# ------------------------------------------------------------------ auditoria / terminais
@bp.route("/auditoria")
@admin_required
def auditoria():
    filtros = ["1=1"]
    params = []
    if request.args.get("q"):
        filtros.append("(usuario LIKE ? OR acao LIKE ? OR detalhes LIKE ?)")
        like = f"%{request.args.get('q')}%"
        params += [like, like, like]
    if request.args.get("acao"):
        filtros.append("acao = ?")
        params.append(request.args.get("acao"))
    sql = f"SELECT * FROM auditoria WHERE {' AND '.join(filtros)} ORDER BY id DESC"
    itens, total, page, pages = paginate(sql, tuple(params),
                                         request.args.get("page", 1, type=int), per_page=50)
    acoes = todos("SELECT DISTINCT acao FROM auditoria ORDER BY acao")
    return render_template("admin/auditoria.html", itens=itens, total=total, page=page,
                           pages=pages, acoes=acoes, termo=request.args.get("q", ""),
                           acao_atual=request.args.get("acao", ""))


@bp.route("/terminais")
@admin_required
def terminais():
    itens = todos("""SELECT t.*, u.nome AS usuario FROM terminais t
                     LEFT JOIN usuarios u ON u.id=t.usuario_id
                     ORDER BY t.ultimo_acesso DESC""")
    return render_template("admin/terminais.html", itens=itens)


@bp.route("/limpar-auditoria", methods=["POST"])
@admin_required
def limpar_auditoria():
    db = get_db()
    antes = db.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0]
    db.execute("""DELETE FROM auditoria WHERE id NOT IN
                  (SELECT id FROM auditoria ORDER BY id DESC LIMIT 200)""")
    db.commit()
    depois = db.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0]
    registrar_acao("limpar_auditoria", "auditoria", None, f"{antes} -> {depois} linhas")
    flash(f"Log reduzido de {antes} para {depois} linhas (as 200 mais recentes foram mantidas).", "ok")
    return redirect(url_for("admin.auditoria"))
