#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$0")"

pause_on_error() {
  local code=$?
  if [ "$code" -ne 0 ]; then
    echo
    echo "No se pudo completar el arranque. El detalle aparece arriba."
    echo "Puedes volver a abrir este archivo cuando lo hayas corregido."
    read -r -p "Pulsa Enter para cerrar... " _ || true
  fi
}
trap pause_on_error EXIT

if [ "$(uname -s)" != "Darwin" ]; then
  echo "Este lanzador es para macOS."
  exit 1
fi

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v brew >/dev/null 2>&1; then
  echo "YouCanDownload necesita Homebrew para instalar sus componentes gratuitos."
  echo "Instálalo una vez desde https://brew.sh y vuelve a abrir este archivo."
  echo "Se abrirá la página oficial de Homebrew."
  open https://brew.sh
  exit 1
fi

brew_path="$(command -v brew)"
packages=()
needs_install=0
for package in python@3.12 ffmpeg node@22; do
  if ! "$brew_path" list --versions "$package" >/dev/null 2>&1; then
    packages+=("$package")
    needs_install=1
  fi
done
if [ "$needs_install" -eq 1 ]; then
  echo "Instalando componentes gratuitos: ${packages[*]}"
  echo "La primera instalación puede tardar varios minutos."
  "$brew_path" install "${packages[@]}"
fi

python_bin="$("$brew_path" --prefix python@3.12)/bin/python3.12"
node_bin="$("$brew_path" --prefix node@22)/bin"
ffmpeg_bin="$("$brew_path" --prefix ffmpeg)/bin"
export PATH="$node_bin:$ffmpeg_bin:$PATH"
state_dir="$HOME/Library/Application Support/YouCanDownload"
mkdir -p "$state_dir"
if [ ! -x "$state_dir/venv/bin/python" ]; then
  "$python_bin" -m venv "$state_dir/venv"
fi
requirements_hash="$(shasum -a 256 requirements.txt | cut -d ' ' -f 1)"
installed_hash=""
if [ -f "$state_dir/requirements.sha256" ]; then
  installed_hash="$(cat "$state_dir/requirements.sha256")"
fi
if [ "$requirements_hash" != "$installed_hash" ]; then
  echo "Preparando el motor de YouCanDownload..."
  "$state_dir/venv/bin/python" -m pip install --upgrade pip
  "$state_dir/venv/bin/python" -m pip install -r requirements.txt
  printf '%s\n' "$requirements_hash" > "$state_dir/requirements.sha256"
fi

export DOWNLOAD_DIR="$state_dir/temporary"
export YCD_LOCAL=1
# A private server setting must not be inherited accidentally from a shell.
unset APP_ACCESS_CODE
"$state_dir/venv/bin/python" mac_launcher.py "$@"
