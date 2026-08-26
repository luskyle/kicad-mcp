#!/usr/bin/env bash
#
# 从 KiCad 源码仓库的 api/proto 生成 Python protobuf 绑定到 src/kicad_mcp/proto/
#
# 用法:
#   ./gen_proto.sh            # 使用默认 python (base 环境的 python)
#   PYTHON=/path/to/python ./gen_proto.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROTO_DIR="$REPO_ROOT/api/proto"
OUT_DIR="$SCRIPT_DIR/src/kicad_mcp/proto"

PYTHON="${PYTHON:-python3}"

# grpc_tools 自带的 google/protobuf well-known types 路径
GRPC_TOOLS_PROTO="$("$PYTHON" -c 'import grpc_tools, os; print(os.path.join(os.path.dirname(grpc_tools.__file__), "_proto"))')"

echo ">>> proto dir : $PROTO_DIR"
echo ">>> output    : $OUT_DIR"

if [ ! -d "$PROTO_DIR" ]; then
    echo "ERROR: $PROTO_DIR 不存在" >&2
    exit 1
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

# 一次性编译所有 .proto（import 相对 proto 根）
"$PYTHON" -m grpc_tools.protoc \
    -I "$PROTO_DIR" \
    -I "$GRPC_TOOLS_PROTO" \
    --python_out="$OUT_DIR" \
    $(find "$PROTO_DIR" -name '*.proto')

# 生成的目录都需要是包
find "$OUT_DIR" -type d -exec touch "{}/__init__.py" \;

echo ">>> done. 绑定已生成到 $OUT_DIR"
