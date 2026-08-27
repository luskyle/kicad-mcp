"""绘制 keyboard-89 键盘布局原理图：放置核心元件 + 读回引脚。

用法: PYTHONPATH=src python tests/draw_kb_layout.py
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


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            lib = "keyboard-89_local"

            print("【1】放置核心元件")
            # USB Type-C 输入
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": lib, "entry_name": "USBC",
                              "x_mm": 60, "y_mm": 55, "reference": "J1", "value": "USBC"}))
            # LDO 稳压
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": lib, "entry_name": "LDO",
                              "x_mm": 60, "y_mm": 140, "reference": "U2", "value": "LDO"}))
            # 去耦/滤波电容
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": lib, "entry_name": "C-100nF",
                              "x_mm": 115, "y_mm": 175, "reference": "C1", "value": "100nF"}))
            # 主控 RP2040
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": lib, "entry_name": "RP2040",
                              "x_mm": 200, "y_mm": 110, "reference": "U1", "value": "RP2040"}))
            # 12MHz 晶振
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": lib, "entry_name": "YXC",
                              "x_mm": 235, "y_mm": 25, "reference": "Y1", "value": "12MHz"}))
            # SPI Flash
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": lib, "entry_name": "GD25Q16E",
                              "x_mm": 350, "y_mm": 55, "reference": "U3", "value": "GD25Q16E"}))
            # 调试口 SWD
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": lib, "entry_name": "PIN-5P",
                              "x_mm": 355, "y_mm": 180, "reference": "J2", "value": "SWD"}))

            print("【2】读回关键引脚")
            for ref in ("U1", "U2", "J1", "U3", "Y1", "J2"):
                print(await call(session, "kicad_sch_get_symbol_pins", {"reference": ref}))


if __name__ == "__main__":
    asyncio.run(main())
