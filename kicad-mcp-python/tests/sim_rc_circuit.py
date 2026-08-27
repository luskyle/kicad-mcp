"""通过 MCP 会话验证 kicad_sch_simulate 工具（模拟 AI 客户端调用）。"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
sys.path.insert(0, SRC)

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def call(session, name, args) -> str:
    res = await session.call_tool(name, args)
    return "\n".join(getattr(c, "text", str(c)) for c in res.content)


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("可用工具:", names)
            print("kicad_sch_simulate 已注册:", "kicad_sch_simulate" in names)

            print("\n===== 仿真 RC 电路（自动向量 + .ic 从 0V 充电）=====")
            out = await call(session, "kicad_sch_simulate", {
                "extra": ".ic v(/OUT)=0",
                "points": 40,
            })
            print(out)


if __name__ == "__main__":
    asyncio.run(main())
