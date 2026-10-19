import re, json, time, io, zipfile, urllib.request, urllib.parse, http.cookiejar, sys

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5099"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def get(u):
    try:
        r = op.open(BASE + u)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def post(u, d=None):
    req = urllib.request.Request(BASE + u, data=urllib.parse.urlencode(d or {}).encode())
    try:
        r = op.open(req)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def raw_post(u, campos, arquivos=None):
    """POST multipart com campos de texto e (opcionalmente) arquivos."""
    limite = "----fs%d" % int(time.time() * 1000)
    partes = []
    for nome, valor in campos:
        partes.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                       % (limite, nome, valor)).encode())
    for nome, (nome_arq, dados) in (arquivos or {}).items():
        partes.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                       "Content-Type: text/csv\r\n\r\n" % (limite, nome, nome_arq)).encode())
        partes.append(dados)
        partes.append(b"\r\n")
    partes.append(("--%s--\r\n" % limite).encode())
    req = urllib.request.Request(BASE + u, data=b"".join(partes),
                                 headers={"Content-Type": "multipart/form-data; boundary=" + limite})
    try:
        r = op.open(req)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def text(b):
    return b.decode("utf-8", "replace")

def limpo(h):
    return re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", text(h)))

def csrf(h):
    m = (re.search(r'name="csrf_token"[^>]*value="([^"]+)"', text(h))
         or re.search(r'value="([^"]+)"[^>]*name="csrf_token"', text(h)))
    return m.group(1) if m else None

erros = []
def checa(nome, cond, extra=""):
    print(("OK  " if cond else "FALHA") + " " + nome + ((" -> " + extra[:400]) if extra and not cond else ""))
    if not cond:
        erros.append(nome)

def login(login, senha):
    global cj, op
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    s, h = get("/login")
    post("/login", {"login": login, "senha": senha, "csrf_token": csrf(h)})

def cnpj_unico():
    random_seed = int(time.time() * 1000) % 10 ** 9
    import random
    random.seed(random_seed)
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    base = [random.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    def dig(nums, pesos):
        soma = sum(n * p for n, p in zip(nums, pesos))
        r = soma % 11
        return 0 if r < 2 else 11 - r
    base.append(dig(base, pesos1))
    base.append(dig(base, [6] + pesos1))
    d = "".join(map(str, base))
    return "%s.%s.%s/%s-%s" % (d[0:2], d[2:5], d[5:8], d[8:12], d[12:])


# ------------------------------------------------------------------ 1. perfis
print("== permissões por perfil ==")
login("caixa", "caixa123")
for rota, esperado in [("/pdv/", 200), ("/produtos/", 200), ("/admin/usuarios", 403),
                       ("/backup/", 403), ("/relatorios/auditoria", 403), ("/admin/empresa", 403)]:
    s, h = get(rota)
    checa("caixa %s -> %d" % (rota, esperado), s == esperado, "recebido %s" % s)

login("gerente", "gerente123")
for rota, esperado in [("/relatorios/", 200), ("/produtos/novo", 200), ("/admin/usuarios", 403),
                       ("/backup/", 403), ("/vendas/", 200)]:
    s, h = get(rota)
    checa("gerente %s -> %d" % (rota, esperado), s == esperado, "recebido %s" % s)

# ------------------------------------------------------- 2. admin e backups
print("\n== admin, backup e restauração ==")
login("admin", "admin123")

s, h = get("/pdv/buscar?codigo=dipirona")
j = json.loads(text(h))
p = j.get("produto") or j["resultados"][0]
payload = {"cliente_id": None,
           "itens": [{"produto_id": p["id"], "quantidade": 1,
                      "preco_unitario": p["preco_venda"], "desconto": 0}],
           "pagamentos": [{"forma": "pix", "valor": p["preco_venda"], "parcelas": 1}],
           "terminal": "BACKUP-TEST"}
req = urllib.request.Request(BASE + "/pdv/venda", data=json.dumps(payload).encode(),
                             headers={"Content-Type": "application/json"})
try:
    r = op.open(req); s, h = r.status, r.read()
except urllib.error.HTTPError as e:
    s, h = e.code, e.read()
checa("venda para backup", s == 201, "%s %s" % (s, text(h)[:200]))
venda_ref = json.loads(text(h)) if s == 201 else {}

s, h = get("/backup/")
token = csrf(h)
s, h = post("/backup/criar", {"observacao": "backup de teste e2e", "csrf_token": token})
checa("criar backup", s in (200, 302), str(s))

s, h = get("/backup/")
ids = re.findall(r"/backup/baixar/(\d+)", text(h))
checa("histórico de backups", len(ids) >= 1, "ids=%s" % ids)

if ids:
    s, b = get("/backup/baixar/%s" % ids[0])
    checa("baixar backup (.zip)", s == 200 and b[:2] == b"PK", "status=%s inicio=%r" % (s, b[:20]))
    if b[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(b))
        nomes = z.namelist()
        print("     zip:", nomes[:8], "..." if len(nomes) > 8 else "")
        checa("zip contém banco", any(n.endswith("farmacia.db") for n in nomes), str(nomes))
        checa("zip contém manifesto", any("manifest" in n for n in nomes), str(nomes))
        checa("zip contém fotos", any("uploads" in n for n in nomes), str(nomes))

    s, h = get("/backup/")
    token = csrf(h)
    s, h = post("/backup/restaurar", {"backup_id": ids[0], "csrf_token": token,
                                      "confirmacao": "RESTAURAR"})
    checa("restaurar backup", s in (200, 302), "status=%s %s" % (s, limpo(h)[:250]))
    # o helper segue o redirect: o flash já vem na própria resposta do POST
    checa("flash de restauração ok", "restaurado com sucesso" in text(h).lower(), limpo(h)[:250])

    s, h = get("/")
    checa("dashboard após restaurar", s == 200 and "R$" in text(h), str(s))
    if venda_ref:
        s, h = get("/vendas/%d" % venda_ref["id"])
        checa("venda presente após restaurar", s == 200, str(s))

# --------------------------------------------------------- 3. importação CSV
print("\n== importação de CSV (outros sistemas) ==")
s, h = get("/backup/importar")
checa("tela importar", s == 200, str(s))
token = csrf(h)

codigo1 = "IMP%d" % (int(time.time()) % 100000)
codigo2 = "IMQ%d" % (int(time.time()) % 100000)
csv_produtos = (
    "codigo;nome;principio_ativo;laboratorio;apresentacao;tarja;preco_custo;preco_venda;"
    "estoque;estoque_minimo;ean\n"
    "%s;Dipirona Import 500mg;Dipirona;Lab Import;Caixa 10;livre;4,50;9,90;30;5;7891106111613\n"
    "%s;Omeprazol Import 20mg;Omeprazol;Lab Import;Caixa 28;amarela;10,00;22,50;20;5;7896004712345\n"
    % (codigo1, codigo2))

s, h = raw_post("/backup/importar",
                [("modelo", "auto"), ("tabela", "produtos"), ("csrf_token", token)],
                {"arquivo": ("produtos.csv", csv_produtos.encode())})
resp = text(h)
checa("etapa 2 da importação (mapeamento)", s == 200 and "destino" in resp,
      "status=%s %s" % (s, limpo(h)[:300]))
destino = re.search(r'name="destino"[^>]*value="([^"]+)"', resp)
destino = destino.group(1) if destino else ""
colunas = re.findall(r'name="coluna"\s+value="(\d+)"', resp) or \
          re.findall(r'value="(\d+)"[^>]*name="coluna"', resp)
# pega o <option selected> de cada <select name="campo">
sels = re.findall(r'<select name="campo"[^>]*>(.*?)</select>', resp, re.S)
campos = []
for bloco in sels:
    m = re.search(r'<option value="([^"]*)"[^>]*selected', bloco)
    campos.append(m.group(1) if m else "")
pares = [(c, v) for c, v in zip(colunas, campos) if v]
checa("mapeamento automático de colunas", len(pares) >= 6, "pares=%s" % pares)

form = [("destino", destino), ("tabela", "produtos"), ("acao", "criar"), ("csrf_token", token)]
form += [("coluna", c) for c, _ in pares] + [("campo", v) for _, v in pares]
s, h = post("/backup/importar/aplicar", None) if False else (None, None)
req = urllib.request.Request(BASE + "/backup/importar/aplicar",
                             data=urllib.parse.urlencode(form, doseq=True).encode())
try:
    r = op.open(req); s, h = r.status, r.read()
except urllib.error.HTTPError as e:
    s, h = e.code, e.read()
checa("aplicar importação", s in (200, 302), "status=%s %s" % (s, limpo(h)[:300]))
checa("resultado com criados", "criado" in text(h).lower(), limpo(h)[:300])

s, h = get("/produtos/?q=Import")
checa("produto importado listado", s == 200 and "Import" in text(h), str(s))

# ------------------------------------------------------------ 4. export JSON
print("\n== exportações ==")
s, h = get("/backup/export/json")
checa("export json", s == 200 and b"sistema" in h, str(s))
s, h = get("/backup/export/todos-csv")
checa("export todos csv (zip)", s == 200 and h[:2] == b"PK", "status=%s" % s)

# -------------------------------------------------------------- 5. usuários
print("\n== usuários ==")
s, h = get("/admin/usuarios")
checa("lista usuários", s == 200 and "admin" in text(h), str(s))
s, h = get("/admin/usuarios/novo")
token = csrf(h)
s, h = post("/admin/usuarios/novo", {"nome": "Teste E2E", "login": "teste%d" % (int(time.time()) % 10000),
                                     "senha": "senha123", "confirmacao": "senha123",
                                     "perfil": "caixa", "ativo": "1", "csrf_token": token})
checa("criar usuário", s in (200, 302), "status=%s %s" % (s, limpo(h)[:250]))

s, h = get("/conta/senha")
token = csrf(h)
s, h = post("/conta/senha", {"senha_atual": "admin123", "senha_nova": "admin12345",
                             "confirmacao": "admin12345", "csrf_token": token})
checa("trocar senha", s in (200, 302), "status=%s %s" % (s, limpo(h)[:250]))
s, h = get("/conta/senha")
s, h = post("/conta/senha", {"senha_atual": "admin12345", "senha_nova": "admin123",
                             "confirmacao": "admin123", "csrf_token": csrf(h)})
checa("reverter senha", s in (200, 302), "status=%s" % s)

# --------------------------------------------------------------- 6. estoque
print("\n== estoque ==")
s, h = get("/estoque/entrada")
token = csrf(h)
form_entrada = [("fornecedor_id", "1"), ("numero", "NFTESTE%d" % (int(time.time()) % 10000)),
                ("data_emissao", "2026-10-18"), ("observacao", "teste e2e"), ("csrf_token", token),
                ("produto_id", "1"), ("quantidade", "10"), ("lote", "LTTESTE1"),
                ("validade", "2027-12-31"), ("preco_unitario", "5,00")]
s, h = post("/estoque/entrada", form_entrada)
checa("entrada de estoque", s in (200, 302), "status=%s %s" % (s, limpo(h)[:250]))

# saída manual
s, h = get("/estoque/")
token = csrf(h)
form_saida = [("produto_id", "1"), ("quantidade", "2"), ("motivo", "perda"),
              ("observacao", "teste e2e"), ("csrf_token", token)]
s, h = post("/estoque/saida", form_saida)
checa("saída manual de estoque", s in (200, 302), "status=%s %s" % (s, limpo(h)[:250]))

s, h = get("/estoque/?aba=inventario")
checa("inventário (imprimir)", s == 200, str(s))
s, h = get("/estoque/?aba=lotes")
checa("aba lotes", s == 200, str(s))
s, h = get("/estoque/?aba=vencimentos")
checa("aba validades", s == 200, str(s))

# ---------------------------------------------------------- 7. empresa/params
print("\n== empresa e parâmetros ==")
s, h = get("/admin/empresa")
token = csrf(h)
s, h = post("/admin/parametros", {"empresa_nome": "Vida Plena Drogaria", "empresa_cnpj": "12.345.678/0001-95",
                                  "empresa_telefone": "(00) 3222-1000", "csrf_token": token})
checa("salvar parâmetros", s in (200, 302), "status=%s %s" % (s, limpo(h)[:250]))
s, h = get("/")
checa("nome da empresa refletido", "Vida Plena" in text(h), str(s))

print()
print("FALHAS:", erros if erros else "nenhuma")
