"""矩阵页 keyboard_matrix.kicad_sch：3x5 按键矩阵（跨页全局标签 R/C）。

用法: PYTHONPATH=src python tests/draw_matrix_page.py
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
ROWS, COLS = 3, 5
X0, Y0 = 100.0, 60.0
COL_GAP, ROW_GAP = 28.0, 22.0


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

            idx = 1
            for r in range(ROWS):
                for c in range(COLS):
                    await call(session, "kicad_sch_add_symbol",
                               {"lib_nickname": "keyboard-89_local",
                                "entry_name": "TC-6601-5-160G",
                                "x_mm": X0 + c * COL_GAP, "y_mm": Y0 + r * ROW_GAP,
                                "reference": f"K{idx}", "value": ""})
                    idx += 1

            syms = _read_symbols()
            for ref in sorted(syms):
                if not re.match(r"K\d+", ref):
                    continue
                num = int(ref[1:])
                r = (num - 1) // COLS
                c = (num - 1) % COLS
                for pn, net in (("1", f"C{c+1}"), ("2", f"C{c+1}"),
                                ("3", f"R{r+1}"), ("4", f"R{r+1}")):
                    ix, iy = syms[ref]["pins"][pn]
                    dx, dy = dir_for(syms[ref], ix, iy)
                    ex = round((ix / MM + dx) / GRID) * GRID
                    ey = round((iy / MM + dy) / GRID) * GRID
                    await call(session, "kicad_sch_add_line",
                               {"x1_mm": ix / MM, "y1_mm": iy / MM, "x2_mm": ex, "y2_mm": ey})
                    await call(session, "kicad_sch_add_label",
                               {"label_type": "global", "text": net, "x_mm": ex, "y_mm": ey})

            await call(session, "kicad_sch_add_text",
                       {"text": "按键矩阵页: 3x5 (示意, 完整 5x22 见 keyboard-89.sch)",
                        "x_mm": X0, "y_mm": Y0 - 15, "height_mm": 3.5})
            print(await call(session, "kicad_save_document", {}))


if __name__ == "__main__":
    asyncio.run(main())
