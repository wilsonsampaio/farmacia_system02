#!/usr/bin/env python3
"""
FarmaciaSystem - Ponto de entrada do servidor.

Uso:
    python3 run.py                 # inicia em 0.0.0.0:5000 (acessível pela rede)
    FARMACIA_PORTA=8080 python3 run.py
    python3 run.py --debug         # modo desenvolvimento
"""
import argparse
import os
import socket
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def ip_local():
    """Descobre o IP da máquina na rede local (computadores clientes usarão este endereço)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    parser = argparse.ArgumentParser(description="Servidor FarmaciaSystem")
    parser.add_argument("--host", default=os.environ.get("FARMACIA_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("FARMACIA_PORTA", "5000")))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    from farmacia import create_app

    app = create_app()
    ip = ip_local()
    barra = "=" * 64
    print(barra)
    print("  FARMACIASYSTEM - Sistema de Gestão de Farmácia")
    print(barra)
    print(f"  Servidor local : http://127.0.0.1:{args.port}")
    print(f"  Rede local     : http://{ip}:{args.port}   <-- use nas outras máquinas")
    print(f"  Banco de dados : {app.config['DATABASE']}")
    print(f"  Backups        : {app.config['BACKUP_DIR']}")
    print(barra)
    print("  Pressione CTRL+C para encerrar.")
    print(barra)
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
