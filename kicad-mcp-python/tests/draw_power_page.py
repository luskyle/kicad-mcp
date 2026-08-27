"""电源页 keyboard_power.kicad_sch：USBC + LDO + 去耦电容 + 跨页全局标签。

用法: PYTHONPATH=src python tests/draw_power_page.py
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

            print("【1】清空 + 放置")
            await clear_all(session, "symbol", ["Symbol"])
            await clear_all(session, "line", ["Line"])
            await clear_all(session, "label", ["LocalLabel", "GlobalLabel", "DirectiveLabel"])
            await clear_all(session, "text", ["Text"])

            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "keyboard-89_local", "entry_name": "USBC",
                        "x_mm": 100, "y_mm": 60, "reference": "J1", "value": "USBC"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "keyboard-89_local", "entry_name": "LDO",
                        "x_mm": 100, "y_mm": 170, "reference": "U2", "value": "LDO"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "keyboard-89_local", "entry_name": "C-100nF",
                        "x_mm": 160, "y_mm": 210, "reference": "C1", "value": "100nF"})
            # PWR_FLAG 驱动
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 93, "y_mm": 28, "reference": "PWRV"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 107, "y_mm": 183, "reference": "PWR3"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 93, "y_mm": 183, "reference": "PWR0"})

            print("【2】连线（label 全局跨页）")
            syms = _read_symbols()

            async def wire(ref, pin, net, gtype="global"):
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

            # USBC 电源/地
            await wire("J1", "2", "VBUS")
            await wire("J1", "11", "VBUS")
            await wire("J1", "1", "0")
            await wire("J1", "12", "0")
            await wire("J1", "13", "0")
            await wire("J1", "14", "0")
            # USBC 数据（跨页 -> 主控）
            await wire("J1", "6", "USB_DP")
            await wire("J1", "7", "USB_DM")
            # USBC 未用引脚 -> GND
            for pn in ("3", "4", "5", "8", "9", "10"):
                await wire("J1", pn, "0")
            # LDO
            await wire("U2", "3", "VBUS")
            await wire("U2", "2", "3V3")
            await wire("U2", "1", "0")
            # C1 去耦
            await wire("C1", "1", "3V3")
            await wire("C1", "2", "0")
            # PWR_FLAG
            await wire("PWRV", "1", "VBUS")
            await wire("PWR3", "1", "3V3")
            await wire("PWR0", "1", "0")

            await call(session, "kicad_sch_add_text",
                       {"text": "电源页: USB Type-C + LDO 3.3V + 去耦", "x_mm": 40, "y_mm": 20, "height_mm": 3.5})
            print("【3】保存")
            print(await call(session, "kicad_save_document", {}))


if __name__ == "__main__":
    asyncio.run(main())
