"""Flash 页 keyboard_flash.kicad_sch：GD25Q16E SPI Flash。

用法: PYTHONPATH=src python tests/draw_flash_page.py
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

            await clear_all(session, "symbol", ["Symbol"])
            await clear_all(session, "line", ["Line"])
            await clear_all(session, "label", ["LocalLabel", "GlobalLabel", "DirectiveLabel"])
            await clear_all(session, "text", ["Text"])

            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "keyboard-89_local", "entry_name": "GD25Q16E",
                        "x_mm": 150, "y_mm": 100, "reference": "U3", "value": "GD25Q16E"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 150, "y_mm": 55, "reference": "PWR3"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 150, "y_mm": 150, "reference": "PWR0"})

            syms = _read_symbols()

            async def wire(ref, pin, net):
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
                           {"label_type": "global", "text": net, "x_mm": ex, "y_mm": ey})

            await wire("U3", "1", "FLASH_CS")
            await wire("U3", "2", "FLASH_SD1")    # SO = MISO -> SD1
            await wire("U3", "3", "3V3")           # WP# 禁写保护
            await wire("U3", "4", "0")
            await wire("U3", "5", "FLASH_SD0")    # SI = MOSI -> SD0
            await wire("U3", "6", "FLASH_SCLK")
            await wire("U3", "7", "3V3")           # HOLD# 禁
            await wire("U3", "8", "3V3")           # VCC
            await wire("PWR3", "1", "3V3")
            await wire("PWR0", "1", "0")

            await call(session, "kicad_sch_add_text",
                       {"text": "SPI Flash 页: GD25Q16E", "x_mm": 40, "y_mm": 20, "height_mm": 3.5})
            print(await call(session, "kicad_save_document", {}))


if __name__ == "__main__":
    asyncio.run(main())
