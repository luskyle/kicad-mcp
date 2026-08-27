"""MCP stdio 端到端：原理图 CRUD + 标签（GetItems/AddLabel/UpdateText/DeleteItem）。

前置条件: 编译版 eeschema 已打开 demos/stickhub/StickHub.kicad_sch。
用法: PYTHONPATH=src python tests/test_mcp_sch_crud.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
sys.path.insert(0, SRC)

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import (  # noqa: E402
    StdioServerParameters,
    stdio_client,
)


async def call(session, name, args) -> str:
    res = await session.call_tool(name, args)
    return "\n".join(getattr(c, "text", str(c)) for c in res.content)


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1) 查询文本（GetItems）
            print("== kicad_sch_get_items(text) ==")
            out = await call(session, "kicad_sch_get_items", {"item_types": "text"})
            print(out)
            lines = [l for l in out.splitlines() if "Text " in l]
            assert any("MCP" in l or "Hello" in l for l in lines), "未读到文本元素"

            # 2) 创建全局标签（AddLabel）
            print("\n== kicad_sch_add_label(global) ==")
            out = await call(session, "kicad_sch_add_label",
                             {"label_type": "global", "text": "MCP_VCC",
                              "x_mm": 320.0, "y_mm": 80.0})
            print(out)

            # 3) 查询标签确认文本
            print("\n== kicad_sch_get_items(global_label) ==")
            out = await call(session, "kicad_sch_get_items", {"item_types": "global_label"})
            print(out)
            assert "MCP_VCC" in out, "标签文本未创建成功"

            # 4) 创建文本，更新它，删除它（Update/Delete 全流程）
            # 用唯一名避免之前残留的 TEMP_UPD 干扰
            import uuid
            tag = f"UPD{uuid.uuid4().hex[:6]}"
            tag2 = tag + "V2"

            print("\n== kicad_sch_add_text ==")
            out = await call(session, "kicad_sch_add_text",
                             {"text": tag, "x_mm": 330.0, "y_mm": 80.0})
            print(out)

            out = await call(session, "kicad_sch_get_items", {"item_types": "text"})
            m = re.search(rf"Text id=([0-9a-f-]{{36}})[^\n]*{tag}", out)
            assert m, f"未找到刚创建的 {tag} 文本"
            item_id = m.group(1)
            print(f"\n目标文本 id: {item_id}")

            print("\n== kicad_sch_update_text ==")
            out = await call(session, "kicad_sch_update_text",
                             {"item_id": item_id, "text": tag2, "x_mm": 340.0})
            print(out)

            out = await call(session, "kicad_sch_get_items", {"item_types": "text"})
            assert tag2 in out, "更新未生效"
            print(f"更新确认: {tag2} 已生效")

            print("\n== kicad_sch_delete_item ==")
            out = await call(session, "kicad_sch_delete_item", {"item_id": item_id})
            print(out)
            assert "已删除" in out, "删除未生效"

            out = await call(session, "kicad_sch_get_items", {"item_types": "text"})
            assert tag2 not in out, "删除后仍存在"
            print(f"删除确认: {tag2} 已移除")

            print("\n[PASS] MCP 原理图 CRUD + 标签端到端测试通过")


if __name__ == "__main__":
    asyncio.run(main())
