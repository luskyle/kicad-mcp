"""主控页物理电源总线版：3V3/0 用物理水平总线 + 电源符号，其余 label。

用法: PYTHONPATH=src python tests/redraw_main_bus.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
sys.path.insert(0, SRC)

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

sys.path.insert(0, SRC)
from kicad_mcp.tools.schematic import _read_symbols

MM = 10000
GRID = 1.27


async def call(session, name, args) -> str:
    res = await session.call_tool(name, args)
    return "\n".join(getattr(c, "text", str(c)) for c in res.content)


def dir_for(sym, ix, iy):
    cx, cy = sym["x_mm"], sym["y_mm"]
    px, py = ix / MM, iy / MM
    if py < cy - 2:
        return (0, -2.54)
    if py > cy + 2:
        return (0, 2.54)
    if px < cx - 2:
        return (-2.54, 0)
    if px > cx + 2:
        return (2.54, 0)
    return (0, 2.54)


async def clear_all(session, item_types, prefixes):
    out = await call(session, "kicad_sch_get_items", {"item_types": item_types})
    cur = None
    n = 0
    for ln in out.splitlines():
        m = re.search(r"id=([0-9a-f-]{36})", ln)
        if m:
            cur = m.group(1)
        if cur and any(ln.startswith(p) or f" {p}" in ln for p in prefixes):
            await call(session, "kicad_sch_delete_item", {"item_id": cur})
            n += 1
            cur = None
    return n


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("【1】清空")
            await clear_all(session, "symbol", ["Symbol"])
            await clear_all(session, "line", ["Line"])
            await clear_all(session, "label", ["LocalLabel", "GlobalLabel", "DirectiveLabel"])
            await clear_all(session, "text", ["Text"])

            print("【2】放置元件")
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
                        "x_mm": 190, "y_mm": 68.58, "reference": "PWR3"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 190, "y_mm": 172.72, "reference": "PWR0"})

            syms = _read_symbols()

            print("【3】3V3 物理总线")
            top_pins = {"1": 175.26, "10": 170.18, "22": 165.10, "33": 160.02,
                        "42": 154.94, "49": 149.86, "44": 134.62, "48": 129.54,
                        "43": 124.46}  # IOVDD/VREG_VIN/USB_VDD/ADC_AVDD @ y=73.66
            for pn, px in top_pins.items():
                await call(session, "kicad_sch_add_line",
                           {"x1_mm": px, "y1_mm": 73.66, "x2_mm": px, "y2_mm": 68.58})
            await call(session, "kicad_sch_add_line",
                       {"x1_mm": 124.46, "y1_mm": 68.58, "x2_mm": 190.5, "y2_mm": 68.58})
            # +3V3 符号 pin 在 (190.5,68.58)，总线经过；加 label 3V3 便于识别
            await call(session, "kicad_sch_add_label",
                       {"label_type": "local", "text": "3V3", "x_mm": 190.5, "y_mm": 68.58})

            print("【4】0 物理总线")
            gnd_pins = {"57": 167.64, "19": 157.48}  # GND, TESTEN @ y=165.10
            for pn, px in gnd_pins.items():
                await call(session, "kicad_sch_add_line",
                           {"x1_mm": px, "y1_mm": 165.10, "x2_mm": px, "y2_mm": 172.72})
            await call(session, "kicad_sch_add_line",
                       {"x1_mm": 149.86, "y1_mm": 172.72, "x2_mm": 190.5, "y2_mm": 172.72})
            await call(session, "kicad_sch_add_label",
                       {"label_type": "local", "text": "0", "x_mm": 190.5, "y_mm": 172.72})

            print("【5】其他网络 label")
            async def wire(ref, pin, net, gtype="local"):
                sym = syms.get(ref)
                if not sym or pin not in sym.get("pins", {}):
                    return
                ix, iy = sym["pins"][pin]
                dx, dy = dir_for(sym, ix, iy)
                ex = round((ix / MM + dx) / GRID) * GRID
                ey = round((iy / MM + dy) / GRID) * GRID
                await call(session, "kicad_sch_add_line",
                           {"x1_mm": ix / MM, "y1_mm": iy / MM, "x2_mm": ex, "y2_mm": ey})
                await call(session, "kicad_sch_add_label",
                           {"label_type": gtype, "text": net, "x_mm": ex, "y_mm": ey})

            # 1V1: DVDD(23,50) + VREG_VOUT(45)
            await wire("U1", "23", "1V1", "global")
            await wire("U1", "50", "1V1", "global")
            await wire("U1", "45", "1V1", "global")
            # RUN -> 3V3, Y1.GND/J2.3 -> 0, J2.4 -> 3V3
            await wire("U1", "26", "3V3", "global")
            await wire("Y1", "2", "0", "global")
            await wire("Y1", "4", "0", "global")
            await wire("J2", "3", "0", "global")
            await wire("J2", "4", "3V3", "global")
            # 晶振 XIN/XOUT
            await wire("U1", "20", "XIN")
            await wire("Y1", "1", "XIN")
            await wire("U1", "21", "XOUT")
            await wire("Y1", "3", "XOUT")
            # SWD
            await wire("U1", "24", "SWCLK")
            await wire("J2", "1", "SWCLK")
            await wire("U1", "25", "SWD")
            await wire("J2", "2", "SWD")
            # USB
            await wire("U1", "47", "USB_DP", "global")
            await wire("U1", "46", "USB_DM", "global")
            # SPI Flash
            await wire("U1", "56", "FLASH_CS", "global")
            await wire("U1", "52", "FLASH_SCLK", "global")
            await wire("U1", "53", "FLASH_SD0", "global")
            await wire("U1", "55", "FLASH_SD1", "global")
            # 矩阵 GPIO
            for pn, net in (("2", "R1"), ("3", "R2"), ("4", "R3"),
                            ("5", "C1"), ("6", "C2"), ("7", "C3"),
                            ("8", "C4"), ("9", "C5")):
                await wire("U1", pn, net, "global")

            await call(session, "kicad_sch_add_text",
                       {"text": "主控页: RP2040 + 12MHz 晶振 + SWD", "x_mm": 40, "y_mm": 20, "height_mm": 3.5})
            print("【6】保存")
            print(await call(session, "kicad_save_document", {}))


if __name__ == "__main__":
    asyncio.run(main())
