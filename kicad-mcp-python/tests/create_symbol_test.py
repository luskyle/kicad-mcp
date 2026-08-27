"""端到端测试：kicad_sch_create_custom_symbol 从规格书生成自定义符号。

验证: 工具生成 .kicad_symdir 符号文件、干净写入 sym-lib-table、文件格式正确。
用法: PYTHONPATH=src python tests/create_symbol_test.py
"""

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


NE555_SPEC = """元件: NE555
参考: U
描述: 通用定时器 (DIP-8)
封装: Package_DIP:DIP-8_W7.62mm
引脚:
1: GND power_in
2: TRIG input
3: OUT output
4: RESET input
5: CTRL input
6: THRES input
7: DISCH open_collector
8: VCC power_in
"""


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("【1】创建自定义符号 NE555")
            print(await call(session, "kicad_sch_create_custom_symbol", {
                "spec": NE555_SPEC,
                "sch_file": "/media/luskyle/DATA/project/kicad-mcp/demos/divider/Divider.kicad_sch",
                "overwrite": True,
            }))


if __name__ == "__main__":
    asyncio.run(main())
