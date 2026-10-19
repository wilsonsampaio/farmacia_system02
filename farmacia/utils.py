"""Funções utilitárias: formatação, validação, uploads e consultas de apoio."""
import os
import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta

from flask import current_app

TARJAS = [
    ("livre", "Venda livre"),
    ("amarela", "Venda sob prescrição médica"),
    ("vermelha", "Venda sob retenção da receita"),
    ("preta", "Retenção de receita - Portaria 344/98"),
]

FORMAS_PAGAMENTO = [
    ("dinheiro", "Dinheiro"),
    ("debito", "Cartão de débito"),
    ("credito", "Cartão de crédito"),
    ("pix", "PIX"),
    ("ticket", "Ticket / Vale refeição"),
    ("ficha", "Ficha do cliente (fiado)"),
    ("boleto", "Boleto"),
]

PERFIS = [
    ("admin", "Administrador"),
    ("gerente", "Gerente"),
    ("caixa", "Operador de caixa"),
]

CLASSES_TERAPEUTICAS = [
    "Analgésico e antitérmico", "Anti-inflamatório", "Antibiótico", "Antialérgico",
    "Anti-hipertensivo", "Cardiovascular", "Diabetes", "Gastroenterologia",
    "Respiratório e antialérgico", "Dermatológico", "Sistema nervoso central",
    "Hormônios e endocrinologia", "Vitaminas e suplementos", "Ginecologia e obstetrícia",
    "Oftálmico", "Ortopédico e muscular", "Antiparasitário", "Imunização",
    "Antifúngico", "Grapas e soluções", "Higiene e dermocosmético", "Outros",
]


# --------------------------------------------------------------------------- formatação
def brl(valor):
    """Formata um valor monetário no padrão brasileiro: R$ 1.234,56"""
    try:
        valor = float(valor or 0)
    except (TypeError, ValueError):
        valor = 0.0
    texto = f"{valor:,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def inteiro(valor):
    try:
        v = float(valor or 0)
        return str(int(v)) if v == int(v) else f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(valor)


def data_br(data):
    """Converte 'YYYY-MM-DD' ou ISO completo para 'DD/MM/AAAA'."""
    if not data:
        return "-"
    texto = str(data)
    try:
        if len(texto) >= 10 and texto[4] == "-":
            return texto[8:10] + "/" + texto[5:7] + "/" + texto[0:4]
        return texto
    except Exception:
        return texto


def data_hora_br(data):
    if not data:
        return "-"
    texto = str(data)
    try:
        if len(texto) >= 16 and texto[4] == "-":
            return f"{texto[8:10]}/{texto[5:7]}/{texto[0:4]} {texto[11:16]}"
        return texto
    except Exception:
        return texto


def hora(data):
    if not data:
        return "-"
    texto = str(data)
    return texto[11:16] if len(texto) >= 16 else texto


def data_iso(brutal):
    """Converte 'DD/MM/AAAA' (ou ISO) para 'YYYY-MM-DD'. Aceita vazio -> None."""
    if not brutal:
        return None
    texto = str(brutal).strip()
    if not texto:
        return None
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", texto)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", texto)
    if m:
        return m.group(0)
    return texto


def relativo_em(dias):
    return (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")


def dias_ate(data_futura):
    """Quantidade de dias até uma data (negativo = vencida)."""
    if not data_futura:
        return None
    try:
        alvo = datetime.strptime(str(data_futura)[:10], "%Y-%m-%d").date()
        return (alvo - date.today()).days
    except Exception:
        return None


def idade(data_nasc):
    if not data_nasc:
        return None
    try:
        nasc = datetime.strptime(str(data_nasc)[:10], "%Y-%m-%d").date()
        hoje = date.today()
        return hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))
    except Exception:
        return None


# --------------------------------------------------------------------------- validação
def digitos(texto):
    return re.sub(r"\D", "", str(texto or ""))


def cpf_valido(cpf):
    cpf = digitos(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for t in (9, 10):
        soma = sum(int(cpf[i]) * ((t + 1) - i) for i in range(t))
        dig = (soma * 10) % 11
        dig = 0 if dig == 10 else dig
        if dig != int(cpf[t]):
            return False
    return True


def cnpj_valido(cnpj):
    cnpj = digitos(cnpj)
    if len(cnpj) != 14:
        return False
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]   # 12 primeiros dígitos
    pesos2 = [6] + pesos1                            # 13 primeiros dígitos
    for t, pesos in ((12, pesos1), (13, pesos2)):
        soma = sum(int(cnpj[i]) * pesos[i] for i in range(t))
        resto = soma % 11
        dig = 0 if resto < 2 else 11 - resto
        if dig != int(cnpj[t]):
            return False
    return True


def mascara_cpf(cpf):
    d = digitos(cpf)
    if len(d) != 11:
        return cpf or ""
    return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def mascara_cnpj(cnpj):
    d = digitos(cnpj)
    if len(d) != 14:
        return cnpj or ""
    return f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def mascara_cpf_cnpj(doc):
    d = digitos(doc)
    if len(d) == 11:
        return mascara_cpf(d)
    if len(d) == 14:
        return mascara_cnpj(d)
    return doc or ""


# --------------------------------------------------------------------------- arquivos
def slugificar(texto, limite=60):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:limite] or "arquivo"


EXTENSOES_FOTO = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def salvar_foto(file_storage, subpasta="produtos"):
    """
    Salva uma imagem redimensionada em data/uploads/<subpasta>/.
    Retorna o nome do arquivo salvo ou None (arquivo inválido).
    """
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in EXTENSOES_FOTO:
        return None
    destino_dir = os.path.join(current_app.config["UPLOAD_DIR"], subpasta)
    os.makedirs(destino_dir, exist_ok=True)
    nome = f"{uuid.uuid4().hex[:12]}{ext}"
    caminho = os.path.join(destino_dir, nome)
    file_storage.save(caminho)
    try:
        from PIL import Image

        with Image.open(caminho) as img:
            img = img.convert("RGB")
            img.thumbnail((1200, 1200), Image.LANCZOS)
            if ext in (".jpg", ".jpeg", ".webp", ".bmp"):
                img.save(caminho, "JPEG", quality=86, optimize=True)
            else:
                img.save(caminho, "PNG", optimize=True)
    except Exception:
        if not os.path.exists(caminho):
            return None
    return nome


def apagar_foto(nome, subpasta="produtos"):
    if not nome or "/" in nome or "\\" in nome or ".." in nome:
        return False
    caminho = os.path.join(current_app.config["UPLOAD_DIR"], subpasta, nome)
    if os.path.exists(caminho):
        try:
            os.remove(caminho)
            return True
        except OSError:
            return False
    return False


def caminho_foto(nome, subpasta="produtos"):
    if not nome:
        return None
    if "/" in nome or "\\" in nome or ".." in nome:
        return None
    caminho = os.path.join(current_app.config["UPLOAD_DIR"], subpasta, nome)
    return caminho if os.path.exists(caminho) else None


def tamanho_arquivo(caminho):
    try:
        return os.path.getsize(caminho)
    except OSError:
        return 0


def formatar_tamanho(bytes_):
    bytes_ = float(bytes_ or 0)
    for unidade in ("B", "KB", "MB", "GB"):
        if bytes_ < 1024 or unidade == "GB":
            return f"{bytes_:.1f} {unidade}" if unidade != "B" else f"{int(bytes_)} B"
        bytes_ /= 1024
    return f"{bytes_:.1f} GB"


# --------------------------------------------------------------------------- consultas
def valor_de(registro, chave, padrao=None):
    """Lê um campo de dict, sqlite3.Row ou objeto — tolerante a tipos mistos."""
    if registro is None:
        return padrao
    try:
        return registro[chave]
    except (KeyError, IndexError, TypeError):
        pass
    try:
        getter = getattr(registro, "get", None)
        if getter:
            return getter(chave, padrao)
    except Exception:
        pass
    return padrao


def foto_principal(produto_id):
    from .db import um

    row = um("SELECT arquivo FROM produto_fotos WHERE produto_id = ? ORDER BY principal DESC, ordem, id LIMIT 1",
             (produto_id,))
    return row["arquivo"] if row else None


def estoque_baixo(limite_extra=0):
    from .db import todos

    return todos(
        """SELECT id, nome, codigo, principio_ativo, laboratorio, estoque, estoque_minimo, unidade
           FROM produtos
           WHERE ativo = 1 AND estoque <= estoque_minimo + ?
           ORDER BY (estoque - estoque_minimo), nome""",
        (limite_extra,),
    )


def proximos_vencimento(dias=60):
    from .db import todos

    return todos(
        """SELECT l.id, l.produto_id, p.nome, p.codigo, l.lote, l.validade, l.quantidade
           FROM lotes l JOIN produtos p ON p.id = l.produto_id
           WHERE l.quantidade > 0 AND l.validade IS NOT NULL AND l.validade != ''
             AND date(l.validade) <= date('now', ?)
           ORDER BY date(l.validade) LIMIT 60""",
        (f"+{int(dias)} days",),
    )
