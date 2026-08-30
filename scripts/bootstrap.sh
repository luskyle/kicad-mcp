#!/usr/bin/env bash
set -euo pipefail

INSTALL_SYSTEM_DEPS=0
SKIP_KICAD_BUILD=0
SKIP_TESTS=0
BUILD_NAME="linux-local-release"
JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"

while (($#)); do
  case "$1" in
    --install-system-deps) INSTALL_SYSTEM_DEPS=1 ;;
    --skip-kicad-build) SKIP_KICAD_BUILD=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    --build-name) BUILD_NAME="$2"; shift ;;
    --jobs) JOBS="$2"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_ROOT="$REPO_ROOT/kicad-mcp-python"
BUILD_DIR="$REPO_ROOT/build/$BUILD_NAME"
INSTALL_DIR="$REPO_ROOT/build/install/$BUILD_NAME"
VENV_DIR="$PYTHON_ROOT/.venv"

if ((INSTALL_SYSTEM_DEPS)); then
  if ! command -v apt-get >/dev/null; then
    echo "Automatic system dependency installation currently supports Debian/Ubuntu only." >&2
    exit 1
  fi
  bash "$REPO_ROOT/install-deps.sh"
  sudo apt-get install -y git ninja-build python3-venv
fi

for command_name in git cmake ninja python3; do
  command -v "$command_name" >/dev/null || {
    echo "Missing $command_name. On Debian/Ubuntu rerun with --install-system-deps." >&2
    exit 1
  }
done

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi
VENV_PYTHON="$VENV_DIR/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -e "$PYTHON_ROOT[dev]"

if ((!SKIP_KICAD_BUILD)); then
  cmake -S "$REPO_ROOT" -B "$BUILD_DIR" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$INSTALL_DIR" \
    -DKICAD_BUILD_QA_TESTS=OFF \
    -DKICAD_SCRIPTING_WXPYTHON=OFF
  cmake --build "$BUILD_DIR" --target install --parallel "$JOBS"
fi

KICAD_CLI="$INSTALL_DIR/bin/kicad-cli"
EESCHEMA="$INSTALL_DIR/bin/eeschema"
STOCK_DATA="$INSTALL_DIR/share/kicad"
for path in "$KICAD_CLI" "$EESCHEMA" "$STOCK_DATA"; do
  [[ -e "$path" ]] || { echo "Incomplete runtime, missing: $path" >&2; exit 1; }
done

if ((!SKIP_TESTS)); then
  (
    cd "$PYTHON_ROOT"
    "$VENV_PYTHON" -m pytest -q \
      tests/test_project.py tests/test_runtime.py tests/test_reload_gate.py \
      tests/test_mcp_stdio.py tests/test_geometry.py tests/test_constraint_layout.py \
      tests/test_label_placement.py tests/test_pathfinding.py \
      tests/test_svg_metrics.py tests/test_draw_report.py
  )
fi

CONFIG_DIR="$REPO_ROOT/build/mcp-config"
mkdir -p "$CONFIG_DIR"
"$VENV_PYTHON" - "$VENV_PYTHON" "$KICAD_CLI" "$STOCK_DATA" "$CONFIG_DIR" <<'PY'
import json
import pathlib
import sys

python, cli, stock, directory = sys.argv[1:]
env = {"KICAD_CLI": cli, "KICAD_STOCK_DATA_HOME": stock}
server = {"command": python, "args": ["-m", "kicad_mcp"], "env": env}
path = pathlib.Path(directory)
(path / "vscode-mcp.json").write_text(
    json.dumps({"servers": {"kicad": {"type": "stdio", **server}}}, indent=2) + "\n"
)
(path / "claude-mcp.json").write_text(
    json.dumps({"mcpServers": {"kicad": server}}, indent=2) + "\n"
)
PY

cat <<EOF
Bootstrap complete
  KiCad CLI: $KICAD_CLI
  Eeschema:   $EESCHEMA
  MCP Python: $VENV_PYTHON
  Config:     $CONFIG_DIR
Next: "$EESCHEMA" <project>.kicad_sch
EOF
