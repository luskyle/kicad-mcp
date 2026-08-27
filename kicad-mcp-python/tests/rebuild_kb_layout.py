"""键盘布局：完整清理 + 重连（全部动态读引脚坐标，消除 off_grid/残留 label）。

用法: PYTHONPATH=src python tests/rebuild_kb_layout.py
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


# 网络: (net, [(ref, pin), ...])
NETWORKS = [
    ("3V3", [("U2", "2"), ("C1", "1"), ("J2", "4"), ("U3", "8"), ("U3", "3"),
             ("U3", "7"), ("U1", "26"),
             ("U1", "1"), ("U1", "10"), ("U1", "22"), ("U1", "23"),
             ("U1", "33"), ("U1", "42"), ("U1", "43"), ("U1", "44"),
             ("U1", "48"), ("U1", "49"), ("U1", "50"), ("PWR3", "1")]),
    ("VBUS", [("J1", "2"), ("J1", "11"), ("U2", "3"), ("PWRV", "1")]),
    ("0", [("J1", "1"), ("J1", "12"), ("J1", "13"), ("J1", "14"),
           ("J1", "4"), ("J1", "5"), ("J1", "8"), ("J1", "9"), ("J1", "10"),
           ("U2", "1"), ("C1", "2"), ("U1", "57"), ("U3", "4"), ("J2", "3"),
           ("Y1", "2"), ("Y1", "4"), ("PWR0", "1")]),
    ("USB_DP", [("J1", "6"), ("U1", "47")]),
    ("USB_DM", [("J1", "7"), ("U1", "46")]),
    ("FLASH_CS", [("U1", "56"), ("U3", "1")]),
    ("FLASH_SCLK", [("U1", "52"), ("U3", "6")]),
    ("FLASH_SD0", [("U1", "53"), ("U3", "5")]),
    ("FLASH_SD1", [("U1", "55"), ("U3", "2")]),
    ("SWCLK", [("U1", "24"), ("J2", "1")]),
    ("SWD", [("U1", "25"), ("J2", "2")]),
    ("R1", [("U1", "2")]), ("R2", [("U1", "3")]), ("R3", [("U1", "4")]),
    ("C1", [("U1", "5")]), ("C2", [("U1", "6")]), ("C3", [("U1", "7")]),
    ("C4", [("U1", "8")]), ("C5", [("U1", "9")]),
]


async def delete_items(session, item_types, match_prefixes):
    """删除指定类型且描述匹配前缀的元素。"""
    out = await call(session, "kicad_sch_get_items", {"item_types": item_types})
    cur = None
    deleted = 0
    for ln in out.splitlines():
        m = re.search(r"id=([0-9a-f-]{36})", ln)
        if m:
            cur = m.group(1)
        if cur and any(ln.startswith(p) or f" {p}" in ln for p in match_prefixes):
            await call(session, "kicad_sch_delete_item", {"item_id": cur})
            deleted += 1
            cur = None
    return deleted


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("【1】清理：删 U1/PWR_FLAG/所有 label/所有 wire")
            # 删除 U1, PWR3/0/V 符号
            out = await call(session, "kicad_sch_get_items", {"item_types": "symbol"})
            cur = None
            for ln in out.splitlines():
                m = re.search(r"id=([0-9a-f-]{36})", ln)
                if m:
                    cur = m.group(1)
                if re.search(r"ref=(U1|PWR3|PWR0|PWRV)\b", ln):
                    await call(session, "kicad_sch_delete_item", {"item_id": cur})
            # 所有 label
            n_lab = await delete_items(session, "label", ["LocalLabel", "GlobalLabel", "DirectiveLabel", "HierLabel"])
            # 所有 wire line
            n_line = await delete_items(session, "line", ["Line"])
            print(f"  删 label={n_lab} line={n_line}")

            print("【2】重放 U1 + PWR_FLAG")
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "keyboard-89_local", "entry_name": "RP2040",
                        "x_mm": 200, "y_mm": 110, "reference": "U1", "value": "RP2040"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 66.04, "y_mm": 126, "reference": "PWR3"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 53.34, "y_mm": 150, "reference": "PWR0"})
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 53.34, "y_mm": 28, "reference": "PWRV"})

            print("【3】晶振重连 (OSC->XIN/XOUT)")
            await call(session, "kicad_sch_connect",
                       {"ref_a": "Y1", "pin_a": "1", "ref_b": "U1", "pin_b": "20"})
            await call(session, "kicad_sch_connect",
                       {"ref_a": "Y1", "pin_a": "3", "ref_b": "U1", "pin_b": "21"})

            print("【4】按键矩阵（引出线 + label）")
            syms = _read_symbols()
            for ref in sorted(syms):
                if not re.match(r"K\d+", ref):
                    continue
                num = int(ref[1:])
                r = (num - 1) // 5
                c = (num - 1) % 5
                for pn, net in (("1", f"C{c+1}"), ("2", f"C{c+1}"),
                                ("3", f"R{r+1}"), ("4", f"R{r+1}")):
                    ix, iy = syms[ref]["pins"][pn]
                    dx, dy = dir_for(syms[ref], ix, iy)
                    await call(session, "kicad_sch_add_line",
                               {"x1_mm": ix / MM, "y1_mm": iy / MM,
                                "x2_mm": ix / MM + dx, "y2_mm": iy / MM + dy})
                    await call(session, "kicad_sch_add_label",
                               {"label_type": "local", "text": net,
                                "x_mm": ix / MM + dx, "y_mm": iy / MM + dy})

            print("【5】电源/USB/SPI/调试/GPIO 网络")
            for net, refpins in NETWORKS:
                for ref, pin in refpins:
                    sym = syms.get(ref)
                    if not sym or pin not in sym.get("pins", {}):
                        continue
                    ix, iy = sym["pins"][pin]
                    dx, dy = dir_for(sym, ix, iy)
                    await call(session, "kicad_sch_add_line",
                               {"x1_mm": ix / MM, "y1_mm": iy / MM,
                                "x2_mm": ix / MM + dx, "y2_mm": iy / MM + dy})
                    await call(session, "kicad_sch_add_label",
                               {"label_type": "local", "text": net,
                                "x_mm": ix / MM + dx, "y_mm": iy / MM + dy})

            print("【6】保存")
            print(await call(session, "kicad_save_document", {}))


if __name__ == "__main__":
    asyncio.run(main())
