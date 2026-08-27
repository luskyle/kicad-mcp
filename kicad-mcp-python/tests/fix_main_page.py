"""修复主控页：删除 line/label 后重连，label 吸附 1.27 网格，XIN/XOUT/SWD 用 label。

用法: PYTHONPATH=src python tests/fix_main_page.py
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
    if px < cx - 2:
        return (-2.54, 0)
    if px > cx + 2:
        return (2.54, 0)
    if py < cy - 2:
        return (0, -2.54)
    return (0, 2.54)


async def delete_all(session, item_types, prefixes):
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

            print("【1】删除 line + label")
            nl = await delete_all(session, "line", ["Line"])
            nlab = await delete_all(session, "label", ["LocalLabel", "GlobalLabel", "DirectiveLabel"])
            print(f"  line={nl} label={nlab}")

            print("【2】重连（label 吸附网格）")
            syms = _read_symbols()

            async def wire(ref, pin, net, gtype="local"):
                sym = syms.get(ref)
                if not sym or pin not in sym.get("pins", {}):
                    return
                ix, iy = sym["pins"][pin]
                dx, dy = dir_for(sym, ix, iy)
                ex = round((ix / MM + dx) / GRID) * GRID
                ey = round((iy / MM + dy) / GRID) * GRID
                await call(session, "kicad_sch_add_line",
                           {"x1_mm": ix / MM, "y1_mm": iy / MM,
                            "x2_mm": ex, "y2_mm": ey})
                await call(session, "kicad_sch_add_label",
                           {"label_type": gtype, "text": net, "x_mm": ex, "y_mm": ey})

            # 晶振 XIN/XOUT（local label 同名连接）
            await wire("U1", "20", "XIN")
            await wire("Y1", "1", "XIN")
            await wire("U1", "21", "XOUT")
            await wire("Y1", "3", "XOUT")
            # SWD
            await wire("U1", "24", "SWCLK")
            await wire("J2", "1", "SWCLK")
            await wire("U1", "25", "SWD")
            await wire("J2", "2", "SWD")
            # 电源
            for pn in ("1", "10", "22", "23", "33", "42", "43", "44", "48", "49", "50"):
                await wire("U1", pn, "3V3", "global")
            await wire("U1", "57", "0", "global")
            await wire("U1", "26", "3V3", "global")
            await wire("U1", "19", "0", "global")      # TESTEN 接地
            await wire("U1", "45", "3V3", "global")    # VREG_VOUT -> 3V3
            await wire("Y1", "2", "0", "global")
            await wire("Y1", "4", "0", "global")
            await wire("J2", "3", "0", "global")
            await wire("J2", "4", "3V3", "global")
            await wire("PWR3", "1", "3V3", "global")
            await wire("PWR0", "1", "0", "global")
            # USB 信号
            await wire("U1", "47", "USB_DP", "global")
            await wire("U1", "46", "USB_DM", "global")
            # SPI
            await wire("U1", "56", "FLASH_CS", "global")
            await wire("U1", "52", "FLASH_SCLK", "global")
            await wire("U1", "53", "FLASH_SD0", "global")
            await wire("U1", "55", "FLASH_SD1", "global")
            # 矩阵 GPIO
            for pn, net in (("2", "R1"), ("3", "R2"), ("4", "R3"),
                            ("5", "C1"), ("6", "C2"), ("7", "C3"),
                            ("8", "C4"), ("9", "C5")):
                await wire("U1", pn, net, "global")

            print("【3】保存")
            print(await call(session, "kicad_save_document", {}))


if __name__ == "__main__":
    asyncio.run(main())
