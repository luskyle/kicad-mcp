"""PCB 绘制能力验证：通过 CreateItems 在 PCB 上创建 BoardText。

前置条件: KiCad 的 pcbnew 已打开一个 PCB（本项目用 demos/stickhub/StickHub.kicad_pcb）。

用法:
    PYTHONPATH=src python tests/test_draw_pcb.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_mcp.client import (  # noqa: E402
    DOCTYPE_PCB,
    KiCadClient,
    find_document_socket,
)
from kicad_mcp.proto.board import board_types_pb2  # noqa: E402
from kicad_mcp.proto.common.types import base_types_pb2  # noqa: E402


def main() -> int:
    url, docs = find_document_socket(DOCTYPE_PCB)
    if url is None:
        print("FAIL: 没有可用的 PCB 进程（pcbnew 未运行或未打开 PCB）")
        return 1
    print(f"[OK] PCB 进程 socket: {url}")

    kc = KiCadClient(url, client_name="kicad-mcp-test")
    kc.connect()
    doc = docs[0]
    print(f"[OK] 目标 PCB: {doc.board_filename}")

    header = base_types_pb2.ItemHeader()
    header.document.CopyFrom(doc)

    # 在 F.SilkS 层创建一个 BoardText
    board_text = board_types_pb2.BoardText()
    board_text.layer = board_types_pb2.BL_F_SilkS
    board_text.text.position.x_nm = 120_000_000  # 120mm
    board_text.text.position.y_nm = 80_000_000   # 80mm
    board_text.text.attributes.size.x_nm = 2_000_000  # 2mm 字高
    board_text.text.attributes.size.y_nm = 2_000_000
    board_text.text.text = "MCP-AI"

    resp = kc.create_items(header, [board_text])
    print(f"[..] 整体状态 = {resp.status}")

    ok = True
    for ci in resp.created_items:
        print(f"[..] item 状态 code={ci.status.code} msg={ci.status.error_message!r}")
        if ci.status.code != 1:  # ISC_OK
            ok = False
        if ci.HasField("item"):
            print(f"[..] 返回 item type_url = {ci.item.type_url}")

    if ok:
        print("[OK] PCB 绘制验证通过：成功在 PCB 上创建了文本元素！")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
