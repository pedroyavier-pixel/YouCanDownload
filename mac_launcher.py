"""Start the existing app locally; no browser credentials or remote API needed."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser

ROOT = Path(__file__).resolve().parent
OPENER = build_opener(ProxyHandler({}))  # localhost must never use a system proxy.


def read_health(port):
    try:
        with OPENER.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
            data = json.load(response)
        return data if data.get("application") == "YouCanDownload" else None
    except (OSError, ValueError, URLError):
        return None


def pick_port(shared=False):
    for port in range(8765, 8775):
        health = read_health(port)
        if health and health.get("local") and health.get("ready") and (not shared or health.get("shared")):
            return port, True
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            try:
                connection.bind(("0.0.0.0" if shared else "127.0.0.1", port))
            except OSError:
                continue
        return port, False
    raise RuntimeError("Los puertos 8765–8774 están ocupados. Cierra otra instancia de YouCanDownload.")


def lan_addresses():
    """Inspect macOS interface addresses without contacting an external host."""
    addresses = set()
    for interface in ("en0", "en1", "en2", "en3", "en4", "en5"):
        try:
            result = subprocess.run(["/usr/sbin/ipconfig", "getifaddr", interface], capture_output=True, text=True, timeout=2)
            address = result.stdout.strip()
            socket.inet_aton(address)
            import ipaddress
            ip = ipaddress.ip_address(address)
            if any(ip in ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
                addresses.add(address)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
    return sorted(addresses)


def launch(shared=False):
    addresses = lan_addresses() if shared else []
    if shared and not addresses:
        raise RuntimeError("No se encontró una conexión Wi-Fi/Ethernet privada. Conecta la Mac a tu red y vuelve a abrir el lanzador.")
    port, existing = pick_port(shared)
    local_url = f"http://127.0.0.1:{port}/"
    if existing:
        print("YouCanDownload ya está abierto. Abriendo la página...", flush=True)
        webbrowser.open(local_url)
        return 0
    environment = os.environ.copy()
    environment.update({"YCD_LOCAL":"1", "YCD_SHARED":"1" if shared else "0",
        "YCD_ALLOWED_HOSTS": ",".join(["127.0.0.1", "localhost", *addresses])})
    environment.pop("APP_ACCESS_CODE", None)
    environment.setdefault("DOWNLOAD_DIR", str(Path.home() / "Library/Application Support/YouCanDownload/temporary"))
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "0.0.0.0" if shared else "127.0.0.1",
        "--port", str(port), "--workers", "1", "--no-proxy-headers"], cwd=ROOT, env=environment, start_new_session=True)
    try:
        print("\nIniciando YouCanDownload...", flush=True)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and not stop.is_set():
            if process.poll() is not None:
                raise RuntimeError("El motor se cerró antes de iniciar. Revisa el mensaje de error de arriba.")
            health = read_health(port)
            if health and health.get("local") and health.get("ready"):
                break
            stop.wait(0.3)
        else:
            raise RuntimeError("El servidor no está listo. Comprueba FFmpeg, Node y la instalación de Python.")
        print(f"\nEN ESTA MAC: {local_url}", flush=True)
        for address in addresses:
            print(f"EN TU CELULAR/TABLETA (mismo Wi-Fi): http://{address}:{port}/", flush=True)
        print("\nPega un enlace de YouTube en la página que se abrirá.", flush=True)
        print("Mantén esta ventana abierta y la Mac encendida. Para detener: Control + C.\n", flush=True)
        webbrowser.open(local_url)
        while process.poll() is None and not stop.wait(0.5):
            pass
        return process.returncode or 0
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def main():
    parser = argparse.ArgumentParser(description="Abre YouCanDownload en tu Mac.")
    parser.add_argument("--share", action="store_true", help="Permite acceder desde otros dispositivos de la red privada.")
    args = parser.parse_args()
    try:
        return launch(shared=args.share)
    except (RuntimeError, OSError) as exc:
        print(f"\nNo se pudo iniciar: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
