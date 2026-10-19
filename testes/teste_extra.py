import re, io, json, zipfile, urllib.request, urllib.parse, http.cookiejar, sys, uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5099"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.CookieProcessor if False else urllib.request.HTTPCookieProcessor(cj))

def get(u):
    try:
        r = op.open(BASE + u); return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def raw_post(u, campos, arquivos=None, ctype_extra=None):
    limite = "----fs%x" % uuid.uuid4().int
    partes = []
    for nome, valor in campos:
        partes.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                       % (limite, nome, valor)).encode())
    for nome, (nome_arq, dados, mime) in (arquivos or {}).items():
        partes.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                       "Content-Type: %s\r\n\r\n" % (limite, nome, nome_arq, mime)).encode())
        partes.append(dados)
        partes.append(b"\r\n")
    partes.append(("--%s--\r\n" % limite).encode())
    req = urllib.request.Request(BASE + u, data=b"".join(partes),
                                 headers={"Content-Type": "multipart/form-data; boundary=" + limite})
    try:
        r = op.open(req); return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def text(b): return b.decode("utf-8", "replace")
def csrf(h):
    t = text(h)
    m = (re.search(r'name="csrf_token"[^>]*value="([^"]+)"', t)
         or re.search(r'value="([^"]+)"[^>]*name="csrf_token"', t))
    return m.group(1) if m else None

erros = []
def checa(nome, cond, extra=""):
    print(("OK  " if cond else "FALHA") + " " + nome + ((" -> " + extra[:300]) if extra and not cond else ""))
    if not cond: erros.append(nome)

# login
s, h = get("/login")
s, h = raw_post("/login", [("login", "admin"), ("senha", "admin123"), ("csrf_token", csrf(h))])
checa("login admin", "Administrador" in text(h), str(s))

# ---------- importação JSON de backup (round-trip) ----------
print("\n== importação JSON ==")
# 1) exporta o JSON atual do sistema
s, export = get("/backup/export/json")
checa("exportar json p/ round-trip", s == 200 and export[:1] == b"{", "status=%s" % s)
dados = json.loads(export.decode("utf-8-sig"))
tabelas = dados.get("tabelas") or dados
checa("json exportado tem usuarios", bool(tabelas.get("usuarios")), str(list(tabelas)[:8]))

# 2) acrescenta 1 cliente novo e importa de volta
cliente_nome = "Cliente JSON %s" % uuid.uuid4().hex[:6]
tabelas.setdefault("clientes", []).append(
    {"nome": cliente_nome, "cpf": "52998224725", "celular": "(11) 98888-7777",
     "limite_credito": 500, "ativo": 1})
s, h = get("/backup/")
token = csrf(h)
s, h = raw_post("/backup/importar/json",
                [("confirmacao", "RESTAURAR"), ("csrf_token", token)],
                {"arquivo": ("export.json", json.dumps(dados).encode(), "application/json")})
checa("importar json status", s in (200, 302), "status=%s" % s)
checa("importar json flash ok", "JSON importado com sucesso" in text(h), text(h)[:200])

# 3) sessão continua válida (usuarios preservados) e cliente presente
s, h = get("/clientes/?q=" + urllib.parse.quote(cliente_nome.split()[-1]))
checa("sessão válida após importar json", s == 200 and "Administrador" in text(h), str(s))
checa("cliente do json presente", s == 200 and cliente_nome in text(h), str(s))
s, h = get("/produtos/")
checa("produtos preservados após json", s == 200 and "Medicamento" in text(h), str(s))

# ---------- restauração por upload de .zip ----------
print("\n== restauração por upload .zip ==")
s, h = get("/backup/")
token = csrf(h)
ids = re.findall(r"/backup/baixar/(\d+)", text(h))
if not ids:
    s, h = raw_post("/backup/criar", [("observacao", "base p/ upload"), ("csrf_token", csrf(h) or token)])
    s, h = get("/backup/")
    ids = re.findall(r"/backup/baixar/(\d+)", text(h))
checa("há backup no histórico", bool(ids), str(ids))
s, z = get("/backup/baixar/" + ids[0])
checa("baixar base para upload", s == 200 and z[:2] == b"PK", str(s))
s, h = get("/backup/")
s, h = raw_post("/backup/restaurar",
                [("confirmacao", "RESTAURAR"), ("csrf_token", csrf(h))],
                {"arquivo": ("upload.zip", z, "application/zip")})
checa("restaurar por upload status", s in (200, 302), "status=%s" % s)
checa("restaurar por upload flash", "restaurado com sucesso" in text(h), text(h)[:200])
s, h = get("/")
checa("sistema ok após upload", s == 200 and "R$" in text(h), str(s))

# restauração recusada sem confirmação
s, h = get("/backup/")
s, h = raw_post("/backup/restaurar", [("confirmacao", "nao"), ("csrf_token", csrf(h))],
                {"arquivo": ("x.zip", z, "application/zip")})
checa("restauração recusada sem RESTAURAR", "RESTAURAR" in text(h), text(h)[:200])

print("\nFALHAS:", erros if erros else "nenhuma")
