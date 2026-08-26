"""原理图绘制能力验证：通过 CreateItems 在原理图上创建文本。

前置条件: KiCad 已启动并打开一个原理图（本项目用 demos/stickhub/StickHub.kicad_sch）。

用法:
    PYTHONPATH=src python tests/test_draw.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from google.protobuf import any_pb2  # noqa: E402

from kicad_mcp.client import (  # noqa: E402
    DOCTYPE_SCHEMATIC,
    KiCadClient,
    find_document_socket,
)
from kicad_mcp.proto.common.commands import editor_commands_pb2  # noqa: E402
from kicad_mcp.proto.common.types import base_types_pb2  # noqa: E402
from kicad_mcp.proto.schematic import schematic_types_pb2  # noqa: E402


def main() -> int:
    # 自动发现能处理原理图文档的进程（eeschema）
    url, docs = find_document_socket(DOCTYPE_SCHEMATIC)
    if url is None:
        print("FAIL: 没有可用的原理图进程（KiCad 未运行或未打开原理图）")
        return 1
    print(f"[OK] 原理图进程 socket: {url}")
    kc = KiCadClient(url, client_name="kicad-mcp-test")
    kc.connect()

    doc = docs[0]
    filename = doc.board_filename
    print(f"[OK] 目标原理图: {filename}")

    header = base_types_pb2.ItemHeader()
    header.document.CopyFrom(doc)

    # 创建一个原理图文本
    sch_text = schematic_types_pb2.Text()
    sch_text.text.position.x_nm = 150_000_000  # 150mm
    sch_text.text.position.y_nm = 100_000_000  # 100mm
    sch_text.text.attributes.size.x_nm = 2_540_000  # 2.54mm
    sch_text.text.attributes.size.y_nm = 2_540_000
    sch_text.text.text = "Hello from MCP AI"

    any_item = any_pb2.Any()
    any_item.Pack(sch_text, type_url_prefix="type.googleapis.com")
    print(f"[..] type_url = {any_item.type_url}")

    resp = kc.create_items(header, [sch_text])
    print(f"[..] 整体状态 = {resp.status}")

    for ci in resp.created_items:
        print(f"[..] item 状态 code={ci.status.code} msg={ci.status.error_message!r}")
        if ci.HasField("item"):
            print(f"[..] 返回 item type_url = {ci.item.type_url}")

    # 反查是否创建成功
    try:
        items = kc.get_items(header, [])
        print(f"[..] GetItems 返回 {len(items.items)} 个元素")
    except Exception as exc:
        print(f"[..] GetItems 查询失败: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
