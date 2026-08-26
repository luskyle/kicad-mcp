"""MCP stdio 端到端测试：通过 MCP 协议调用 PCB 绘制工具。

前置条件: KiCad 的 pcbnew 已打开一个 PCB（demos/stickhub/StickHub.kicad_pcb）。

用法:
    PYTHONPATH=src python tests/test_mcp_stdio.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
sys.path.insert(0, SRC)

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import (  # noqa: E402
    StdioServerParameters,
    stdio_client,
)


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"[OK] MCP 工具列表 ({len(names)}): {names}")

            # 1) 调用 PCB 文本绘制工具
            print("\n--- call kicad_pcb_add_text ---")
            res = await session.call_tool(
                "kicad_pcb_add_text",
                {
                    "text": "MCP-END2END",
                    "x_mm": 130.0,
                    "y_mm": 90.0,
                    "layer": "f.silkscreen",
                    "height_mm": 2.0,
                },
            )
            for c in res.content:
                print(getattr(c, "text", c))

            # 2) 查询 PCB 文本元素
            print("\n--- call kicad_get_pcb_items ---")
            res2 = await session.call_tool("kicad_get_pcb_items", {"item_types": "text"})
            for c in res2.content:
                print(getattr(c, "text", c))


if __name__ == "__main__":
    asyncio.run(main())
