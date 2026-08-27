"""主控页 keyboard_main.kicad_sch：RP2040 + 晶振 + SWD + 跨页全局标签。

用法: PYTHONPATH=src python tests/draw_main_page.py
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

sys.path.insert(0, SRC)
from kicad_mcp.tools.schematic import _read_symbols

MM = 10000


async def call(session, name, args) -> str:
    res = await session.call_tool(name, args)
    return "\n".join(getattr(c, "text", str(c)) for c in res.content)


def dir_for(sym, ix, iy):
    cx, cy = sym["x_mm"], sym["y_mm"]
    px, py = ix / MM, iy / MM
    if px < cx - 2:
        return (-2.54, 0)
    if px > cx + 2:
        return (2.54, 0)
    if py < cy - 2:
        return (0, -2.54)
    return (0, 2.54)


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("【1】放置主控页元件")
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "keyboard-89_local", "entry_name": "RP2040",
                        "x_mm": 150, "y_mm": 120, "reference": "U1", "value": "RP2040"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "keyboard-89_local", "entry_name": "YXC",
                        "x_mm": 135, "y_mm": 200, "reference": "Y1", "value": "12MHz"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "keyboard-89_local", "entry_name": "PIN-5P",
                        "x_mm": 280, "y_mm": 55, "reference": "J2", "value": "SWD"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 150, "y_mm": 35, "reference": "PWR3"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 150, "y_mm": 210, "reference": "PWR0"})

            print("【2】晶振连线")
            await call(session, "kicad_sch_connect",
                       {"ref_a": "Y1", "pin_a": "1", "ref_b": "U1", "pin_b": "20"})
            await call(session, "kicad_sch_connect",
                       {"ref_a": "Y1", "pin_a": "3", "ref_b": "U1", "pin_b": "21"})
            # SWD: U1.SWCLK/SWD -> J2
            await call(session, "kicad_sch_connect",
                       {"ref_a": "U1", "pin_a": "24", "ref_b": "J2", "pin_b": "1"})
            await call(session, "kicad_sch_connect",
                       {"ref_a": "U1", "pin_a": "25", "ref_b": "J2", "pin_b": "2"})

            print("【3】网络 label（页内电源 + 跨页全局标签）")
            syms = _read_symbols()

            async def wire_label(ref, pin, net, gtype="global"):
                sym = syms.get(ref)
                if not sym or pin not in sym.get("pins", {}):
                    return
                ix, iy = sym["pins"][pin]
                dx, dy = dir_for(sym, ix, iy)
                await call(session, "kicad_sch_add_line",
                           {"x1_mm": ix / MM, "y1_mm": iy / MM,
                            "x2_mm": ix / MM + dx, "y2_mm": iy / MM + dy})
                await call(session, "kicad_sch_add_label",
                           {"label_type": gtype, "text": net,
                            "x_mm": ix / MM + dx, "y_mm": iy / MM + dy})

            # 主控 3V3 电源（顶部电源引脚）
            for pn in ("1", "10", "22", "23", "33", "42", "43", "44", "48", "49", "50"):
                await wire_label("U1", pn, "3V3", "global")
            # GND
            await wire_label("U1", "57", "0", "global")
            await wire_label("Y1", "2", "0", "global")
            await wire_label("Y1", "4", "0", "global")
            await wire_label("J2", "3", "0", "global")
            await wire_label("J2", "4", "3V3", "global")
            await wire_label("U1", "26", "3V3", "global")   # RUN 上拉
            # PWR_FLAG 驱动
            await wire_label("PWR3", "1", "3V3", "global")
            await wire_label("PWR0", "1", "0", "global")
            # USB 信号（跨页 -> power）
            await wire_label("U1", "47", "USB_DP", "global")
            await wire_label("U1", "46", "USB_DM", "global")
            # SPI Flash（跨页 -> flash）
            await wire_label("U1", "56", "FLASH_CS", "global")
            await wire_label("U1", "52", "FLASH_SCLK", "global")
            await wire_label("U1", "53", "FLASH_SD0", "global")
            await wire_label("U1", "55", "FLASH_SD1", "global")
            # 矩阵 GPIO（跨页 -> matrix）
            for pn, net in (("2", "R1"), ("3", "R2"), ("4", "R3"),
                            ("5", "C1"), ("6", "C2"), ("7", "C3"),
                            ("8", "C4"), ("9", "C5")):
                await wire_label("U1", pn, net, "global")

            print("【4】保存")
            print(await call(session, "kicad_save_document", {}))


if __name__ == "__main__":
    asyncio.run(main())
