#!/usr/bin/env sh
set -eu

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

venv_dir="$repo_root/.venv"
if [ ! -d "$venv_dir" ]; then
    echo "Creating virtual environment at $venv_dir"
    if command -v python3 >/dev/null 2>&1; then
        python3 -m venv "$venv_dir"
    elif command -v python >/dev/null 2>&1; then
        python -m venv "$venv_dir"
    else
        echo "Error: no Python interpreter found. Install Python 3 and try again." >&2
        exit 1
    fi
fi

python="$venv_dir/bin/python"
if [ ! -x "$python" ]; then
    echo "Error: virtual environment Python executable not found at $python" >&2
    exit 1
fi

echo "Upgrading pip..."
"$python" -m pip install --upgrade pip

echo "Installing shared and dev requirements..."
"$python" -m pip install -r src/layers/shared_utils/requirements.txt -r requirements-dev.txt

cat <<'EOF'

Dev environment is ready.
Activate it with:

. .venv/bin/activate
EOF
