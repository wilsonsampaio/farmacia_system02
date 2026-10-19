import re, json, time, urllib.request, http.cookiejar, urllib.parse, sys

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5099"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def get(url):
    try:
        r = op.open(BASE + url)
        return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')

def post(url, dados=None, json_dados=None):
    if json_dados is not None:
        req = urllib.request.Request(BASE + url, data=json.dumps(json_dados).encode(),
                                     headers={'Content-Type': 'application/json'})
    else:
        req = urllib.request.Request(BASE + url, data=urllib.parse.urlencode(dados or {}).encode())
    try:
        r = op.open(req)
        return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')

def csrf(html):
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html) or re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
    return m.group(1) if m else None

def cnpj_unico():
    import random
    from datetime import datetime
    random.seed(int(datetime.now().timestamp() * 1000) % 10 ** 9)
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    base = [random.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    def dig(nums, pesos):
        s = sum(n * p for n, p in zip(nums, pesos))
        r = s % 11
        return 0 if r < 2 else 11 - r
    base.append(dig(base, pesos1))
    base.append(dig(base, [6] + pesos1))
    d = "".join(map(str, base))
    return f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"

erros = []
def checa(nome, cond, extra=""):
    print(("OK  " if cond else "FALHA") + " " + nome + ((" -> " + extra[:400]) if extra and not cond else ""))
    if not cond: erros.append(nome)

# login
s, html = get("/login")
checa("GET /login", s == 200 and "<form" in html, f"status={s}")
s, resp = post("/login", {"login": "admin", "senha": "admin123", "csrf_token": csrf(html)})
s, html = get("/")
checa("login -> dashboard", s == 200 and ("Sair" in html), f"status={s}")
checa("dashboard tem valores", "R$" in html, "")

rotas = ["/produtos/", "/produtos/1", "/produtos/novo", "/produtos/1/editar", "/clientes/", "/clientes/1",
         "/clientes/novo", "/fornecedores/", "/fornecedores/1", "/fornecedores/novo", "/estoque/",
         "/estoque/entrada", "/pdv/", "/vendas/", "/vendas/1", "/relatorios/", "/backup/",
         "/admin/usuarios", "/admin/usuarios/novo", "/admin/empresa", "/admin/auditoria",
         "/admin/terminais", "/backup/importar", "/backup/verificar", "/conta/senha"]
for r in rotas:
    s, h = get(r)
    checa(f"GET {r}", s == 200, f"status={s} {re.sub('<[^>]+>', ' ', h)[:200] if s!=200 else ''}")

# cupons
s, h = get("/vendas/1/cupom")
checa("cupom 80mm", s == 200 and "CUPOM" in h.upper(), f"status={s}")
s, h = get("/vendas/1/cupom?largura=58")
checa("cupom 58mm", s == 200 and "58mm" in h, f"status={s}")

# PDV
s, h = get("/pdv/buscar?codigo=dipirona")
j = json.loads(h)
checa("busca pdv texto", s == 200 and (j.get("produto") or j.get("resultados")), str(j)[:200])
prod = j.get("produto") or j["resultados"][0]
s, h = get(f"/pdv/buscar?codigo={prod.get('ean') or prod['codigo']}")
p = json.loads(h)["produto"]
checa("busca pdv ean", p.get("ean"), "")

venda = {"cliente_id": None,
         "itens": [{"produto_id": p["id"], "quantidade": 2, "preco_unitario": p["preco_venda"], "desconto": 0}],
         "pagamentos": [{"forma": "dinheiro", "valor": round(p["preco_venda"] * 2 + 20, 2), "parcelas": 1}],
         "terminal": "PDV-TESTE", "observacao": "teste e2e"}
s, h = post("/pdv/venda", json_dados=venda)
checa("venda dinheiro", s == 201, f"status={s} corpo={h[:400]}")
v = json.loads(h) if s == 201 else {}
if v:
    print("     ", v.get("numero"), "total:", v.get("total"), "troco:", v.get("troco"))
    s2, h2 = get(v["cupom"]); checa("cupom nova venda", s2 == 200 and "TOTAL" in h2, f"{s2}")
    s2, h2 = get(v["detalhe"]); checa("detalhe nova venda", s2 == 200, f"{s2}")

# ficha
s, h = get("/clientes/api/buscar?q=Maria")
cli = json.loads(h)["clientes"][0]
venda2 = {"cliente_id": cli["id"],
          "itens": [{"produto_id": p["id"], "quantidade": 1, "preco_unitario": p["preco_venda"], "desconto": 0}],
          "pagamentos": [], "terminal": "PDV-TESTE", "observacao": "fiado teste"}
s, h = post("/pdv/venda", json_dados=venda2)
checa("venda na ficha", s == 201, f"status={s} corpo={h[:400]}")

# estoque insuficiente
venda3 = {"cliente_id": None,
          "itens": [{"produto_id": p["id"], "quantidade": 99999, "preco_unitario": p["preco_venda"], "desconto": 0}],
          "pagamentos": [{"forma": "dinheiro", "valor": 10 ** 9, "parcelas": 1}], "terminal": "X"}
s, h = post("/pdv/venda", json_dados=venda3)
checa("venda acima do estoque recusada (400)", s == 400, f"status={s} {h[:300]}")

# desconto inválido
venda4 = {"cliente_id": None,
          "itens": [{"produto_id": p["id"], "quantidade": 1, "preco_unitario": p["preco_venda"], "desconto": 9999}],
          "pagamentos": [{"forma": "dinheiro", "valor": 1, "parcelas": 1}], "terminal": "X"}
s, h = post("/pdv/venda", json_dados=venda4)
checa("desconto inválido recusado (400)", s == 400, f"status={s}")

# cancelar venda
if v.get("id"):
    s, h = get(f"/vendas/{v['id']}")
    s, h = post(f"/vendas/{v['id']}/cancelar", {"motivo": "teste e2e", "confirmar": v["numero"],
                                                "csrf_token": csrf(h)})
    checa("cancelar venda", s in (200, 302), f"status={s} {h[:200]}")
    s, h = get(f"/vendas/{v['id']}")
    checa("detalhe marca cancelada", "cancelada" in h.lower(), f"status={s}")
    s, h = get(f"/vendas/{v['id']}/cupom")
    checa("cupom cancelada", "CANCELADA" in h.upper(), f"status={s}")

# relatórios
slugs = [x.split('?')[0].split('/')[-1] for x in re.findall(r'href="(/relatorios/[^"?]+)', get("/relatorios/")[1])]
slugs = sorted(set(slugs))
print("     relatórios encontrados:", slugs)
for rel in slugs:
    s, h = get(f"/relatorios/{rel}")
    checa(f"relatorio {rel}", s == 200, f"status={s}")
    s, h = get(f"/relatorios/{rel}/csv")
    checa(f"csv {rel}", s == 200, f"status={s}")

# backup
tok = csrf(get("/backup/")[1])
s, h = post("/backup/criar", {"observacao": "teste e2e", "csrf_token": tok})
checa("criar backup", s in (200, 302), f"status={s} {re.sub('<[^>]+>', ' ', h)[:300]}")
s, h = get("/backup/")
checa("backup listado", s == 200 and (".zip" in h or "backup" in h.lower()), f"status={s}")
s, h = get("/backup/export/csv/produtos")
checa("export csv", s == 200, f"status={s}")
s, h = get("/backup/export/json")
checa("export json", s == 200 and "sistema" in h, f"status={s}")
s, h = get("/backup/verificar")
checa("verificar integridade", s == 200, f"status={s}")

# cadastro de produto via POST
s, h = get("/produtos/novo")
token = csrf(h)
form = {"codigo": f"TESTE{int(time.time())%100000}", "nome": "Produto de Teste 999", "principio_ativo": "Teste",
        "laboratorio": "Lab Teste", "apresentacao": "Caixa 10", "tarja": "livre", "unidade": "UN",
        "preco_custo": "5,00", "preco_venda": "10,00", "estoque_minimo": "5", "estoque": "20",
        "csrf_token": token}
s, h = post("/produtos/novo", form)
checa("cadastrar produto", s in (200, 302), f"status={s}")

# cadastro de cliente
s, h = get("/clientes/novo")
token = csrf(h)
s, h = post("/clientes/novo", {"nome": "Cliente de Teste E2E " + str(int(time.time())%1000), "cpf": "",
                               "celular": "(00) 98888-7777", "csrf_token": token})
checa("cadastrar cliente", s in (200, 302), f"status={s}")

# cadastro de fornecedor
s, h = get("/fornecedores/novo")
token = csrf(h)
s, h = post("/fornecedores/novo", {"razao_social": "Fornecedor de Teste E2E " + str(int(time.time())%1000) + " Ltda",
                                   "cnpj": cnpj_unico(), "csrf_token": token})
checa("cadastrar fornecedor", s in (200, 302), f"status={s}")

# sessão
s, h = get("/api/verificar-sessao")
checa("verificar sessao", s == 200 and "expirada" in h, h[:200])
s, h = get("/api/resumo")
checa("api resumo", s == 200, f"status={s}")

print()
print("FALHAS:", erros if erros else "nenhuma")
