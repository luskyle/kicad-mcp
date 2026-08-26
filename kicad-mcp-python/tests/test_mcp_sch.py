"""MCP stdio 端到端测试：通过 MCP 协议调用原理图绘制工具。

前置条件: 编译版 eeschema 已打开 demos/stickhub/StickHub.kicad_sch，
且符号库表含 Device（见仓库记忆）。

用法:
    PYTHONPATH=src python tests/test_mcp_sch.py
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
            print(f"[OK] MCP 工具列表 ({len(names)}):")
            for n in names:
                print("   -", n)

            # 1) 创建原理图文本
            print("\n--- call kicad_sch_add_text ---")
            res = await session.call_tool(
                "kicad_sch_add_text",
                {"text": "MCP-SCH-END2END", "x_mm": 160.0, "y_mm": 80.0},
            )
            for c in res.content:
                print(getattr(c, "text", c))

            # 2) 创建连线
            print("\n--- call kicad_sch_add_line ---")
            res = await session.call_tool(
                "kicad_sch_add_line",
                {"x1_mm": 150.0, "y1_mm": 100.0, "x2_mm": 180.0, "y2_mm": 100.0,
                 "layer": "wire"},
            )
            for c in res.content:
                print(getattr(c, "text", c))

            # 3) 放置符号 Device:R
            print("\n--- call kicad_sch_add_symbol ---")
            res = await session.call_tool(
                "kicad_sch_add_symbol",
                {"lib_nickname": "Device", "entry_name": "R", "x_mm": 170.0,
                 "y_mm": 90.0, "reference": "R2", "value": "4.7k"},
            )
            for c in res.content:
                print(getattr(c, "text", c))

            print("\n[DONE] MCP 原理图端到端测试完成")


if __name__ == "__main__":
    asyncio.run(main())
