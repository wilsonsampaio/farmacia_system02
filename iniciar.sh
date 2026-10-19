#!/usr/bin/env bash
# ============================================================================
#  FarmaciaSystem — inicializador (Linux / macOS)
#  Uso:  ./iniciar.sh              sobe na porta 5000
#        ./iniciar.sh 8080         sobe na porta 8080
#  Na primeira execução cria a pasta data/ com banco, fotos e dados de
#  exemplo (28 medicamentos, clientes, vendas dos últimos 60 dias).
# ============================================================================
set -e
cd "$(dirname "$0")"

PORTA="${1:-${FARMACIA_PORTA:-5000}}"
PY_VENV="./venv/bin/python3"

echo "============================================================"
echo "  FARMACIASYSTEM - Sistema de Gestao de Farmacia"
echo "============================================================"

# 1) escolhe o Python: venv > python3 do sistema
if [ -x "$PY_VENV" ] && "$PY_VENV" -c "import flask" >/dev/null 2>&1; then
    PY="$PY_VENV"
elif command -v python3 >/dev/null 2>&1 && python3 -c "import flask" >/dev/null 2>&1; then
    PY="python3"
    echo "  AVISO: venv nao encontrado/populado; usando python3 do sistema."
else
    # 2) tenta montar o venv automaticamente
    echo "  Instalando dependencias em ./venv (primeira execucao)..."
    python3 -m venv venv 2>/dev/null || true
    if [ ! -x "$PY_VENV" ]; then
        echo "  ERRO: nao foi possivel criar o virtualenv."
        echo "  Instale manualmente:  sudo apt install python3-venv python3-pip"
        echo "  Ou rode:              pip3 install flask pillow"
        exit 1
    fi
    if ! "$PY_VENV" -m pip --version >/dev/null 2>&1; then
        curl -sSLo /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py || true
        "$PY_VENV" /tmp/get-pip.py -q 2>/dev/null || true
        rm -f /tmp/get-pip.py
    fi
    "$PY_VENV" -m pip install -q -r requirements.txt
    PY="$PY_VENV"
fi

echo "  Python          : $PY"
echo "  Porta           : $PORTA"
echo "  Dados           : $(pwd)/data"
echo "  Acessos iniciais: admin/admin123 | gerente/gerente123 | caixa/caixa123"
echo "============================================================"
echo "  Pressione CTRL+C para encerrar."
echo "============================================================"

FARMACIA_PORTA="$PORTA" exec "$PY" run.py
