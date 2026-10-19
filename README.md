# 💊 FarmaciaSystem

Sistema completo de gestão de farmácia: **PDV, estoque por lote e validade (FIFO), cadastros com foto e bula, clientes, fornecedores, fichas de pagamento, relatórios com gráficos, backup/restauração e impressão de cupons térmicos 58/80 mm** — tudo em português, interface rica, funcionando offline e acessível de vários computadores pela rede local.

Feito em **Python (Flask) + SQLite**: não precisa instalar banco de dados, IIS, Apache nem nada além do Python.

---

## 🚀 Como instalar e rodar

### Requisito único
* **Python 3.10 ou superior** — baixe em [python.org](https://www.python.org/downloads/) (no Windows, marque *“Add python.exe to PATH”* na instalação).

### Windows
```
clique duplo em  iniciar.bat
```
Na primeira execução ele mesmo cria o ambiente virtual e instala Flask + Pillow. Depois é só abrir o navegador em `http://localhost:5000`.

### Linux / macOS
```bash
chmod +x iniciar.sh      # só na primeira vez
./iniciar.sh             # porta 5000
./iniciar.sh 8080        # outra porta
```

### Manualmente (qualquer sistema)
```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt      # Windows: venv\Scripts\pip
python3 run.py                                # Windows: python run.py
```

> **Variáveis úteis:** `FARMACIA_PORTA=8080` muda a porta · `FARMACIA_DADOS=/caminho` move o banco/fotos/backups · `python3 run.py --debug` liga o modo desenvolvimento.

---

## 🖥️ Acessando de outros computadores da rede

O servidor escuta em **todas as interfaces**. Ao iniciar, ele mostra o endereço para as outras máquinas:

```
  Servidor local : http://127.0.0.1:5000
  Rede local     : http://192.168.0.12:5000   <-- use nas outras máquinas
```

Basta digitar esse endereço no navegador de qualquer PC/tablet da farmácia (mesmo Wi-Fi). Nada mais é preciso instalar nos clientes.

---

## 🔑 Acessos iniciais

O sistema se auto-popula na primeira execução com dados de exemplo reais (28 medicamentos com foto e bula, 3 fornecedores, 22 clientes, lotes e ~230 vendas dos últimos 60 dias — o dashboard já abre cheio).

| Perfil  | Login     | Senha        | O que pode fazer                                            |
|---------|-----------|--------------|-------------------------------------------------------------|
| Admin   | `admin`   | `admin123`   | Tudo: configurações, usuários, backup, importação           |
| Gerente | `gerente` | `gerente123` | Cadastros, estoque, relatórios, vendas (sem administração)  |
| Caixa   | `caixa`   | `caixa123`   | PDV, vendas, clientes, consulta de medicamentos             |

> Troque as senhas em **Administração → Usuários** antes de usar a sério.

---

## 🧭 O que tem dentro

### PDV (frente de caixa)
* Busca por nome, princípio ativo, código ou **código de barras** (leitor de barras = digitar e Enter).
* Carrinho que **sobrevive a fechar a aba** (salvo por terminal).
* Atalhos: `F2` busca · `F4` cliente · `F7` desconto · `F8` pagamento · `F9` finalizar · `ESC` limpar.
* Dinheiro (com troco), cartão de débito/crédito (parcelamento), Pix, vale e **ficha (fiado)** com limite de crédito.
* Cupom térmico na hora (ver abaixo).

### Estoque por lote e validade
* Entrada de nota fiscal com lote, validade, custo e fornecedor.
* **Baixa automática por FIFO** — o lote vencendo primeiro sai primeiro.
* Alertas de estoque baixo e vencimento em 60 dias no dashboard.
* Saída manual, ajuste por inventário e movimentações auditadas.

### Medicamentos
* Foto da caixa, **bula completa** (indicações, posologia, contraindicações, reações adversas, interações, gravidez, sobredosagem, armazenamento, excipientes), princípio ativo, laboratório, tarja, ANVISA, EAN.
* Ficha do produto com abas: bula · lotes · movimentações · histórico de vendas · fotos.

### Vendas e clientes
* Histórico com cancelamento controlado (exige digitar o número da venda).
* Ficha de pagamento com baixa parcela a parcela.
* Limite de crédito e situação de fiado por cliente.

### Relatórios (13)
Vendas por período/produto/vendedor/forma de pagamento, curva ABC, margem e lucro, estoque, validades, fichas em aberto, clientes, fornecedores e **auditoria de quem fez o quê** — todos com gráficos SVG gerados no servidor (funcionam offline) e exportação CSV.

### Backup compatível com o mercado
* **`.zip` completo** (banco + fotos + manifesto) — é só guardar uma cópia em pendrive/nuvem.
* Restauração por upload ou pelo histórico, sempre com confirmação digitando `RESTAURAR` e backup de segurança automático antes.
* Exportação **JSON** e **CSV de todas as tabelas** (abre no Excel).
* **Importação de outros sistemas**: envie o CSV/TXT/JSON exportado do seu sistema atual (Excel também) e o mapeamento das colunas é detectado automaticamente — revise e importe.

### Impressão de cupom térmico (58 mm e 80 mm)
Página HTML própria com `@page` no tamanho certo — funciona com **qualquer impressora comum** configurada no navegador, sem instalar driver de ESC/POS. Basta marcar “imprimir sem cabeçalho/rodapé” no diálogo do navegador.

---

## 🗂️ Onde ficam os dados

```
data/
├── farmacia.db        banco SQLite (todo o sistema)
├── secret.key        chave de sessão
├── uploads/produtos/  fotos dos medicamentos
└── backups/          backups .zip automáticos e manuais
```

Para migrar a farmácia para outro computador: copie a pasta `data/` e rode o sistema lá — ou faça um backup `.zip` na tela **Backup** e restaure no destino.

---

## 🧰 Solução de problemas

| Sintoma | Solução |
|---|---|
| “Acesso negado” ao abrir o sistema | Libere a porta no firewall (`sudo ufw allow 5000` ou painel do Windows) |
| Outros PCs não abrem | Confiram se estão na mesma rede e usem o IP mostrado ao iniciar |
| Porta 5000 ocupada | `./iniciar.sh 8080` ou `iniciar.bat 8080` |
| Quero recomeçar do zero | Feche o sistema, apague a pasta `data/` e abra de novo (recria com dados de exemplo) |
| Erro “No module named flask” | `pip install flask pillow` (ou recrie o venv como descrito acima) |

---

## 🧩 Detalhes técnicos

* **Python 3 + Flask + SQLite** (arquivo único, sem servidor de banco).
* Camadas: `farmacia/db.py` (banco) · `services.py` (regras: vendas, FIFO, fichas) · `security.py` (login, perfis, auditoria) · `blueprints/` (11 módulos, 80+ rotas) · `templates/` · `static/` (CSS/JS próprio, **zero CDN — funciona offline**).
* Gráficos são SVG desenhados pelo servidor (`charts.py`) — nada de bibliotecas de frontend.
* CSRF, senhas com hash, sessão por terminal e trilha de auditoria completa.
* Seed de demonstração em `seed.py` (roda automaticamente quando o banco está vazio).
