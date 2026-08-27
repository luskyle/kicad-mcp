"""修正键盘布局：重画按键矩阵（精确引脚 label）+ PWR_FLAG 驱动电源 + USBC 接地。

用法: PYTHONPATH=src python tests/fix_kb_layout.py
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


async def call(session, name, args) -> str:
    res = await session.call_tool(name, args)
    return "\n".join(getattr(c, "text", str(c)) for c in res.content)


ROWS, COLS = 3, 5
X0, Y0 = 125.0, 215.0
COL_GAP, ROW_GAP = 15.0, 15.0
MM = 10000


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("【1】删除旧按键矩阵")
            out = await call(session, "kicad_sch_get_items", {"item_types": "symbol"})
            cur = None
            for ln in out.splitlines():
                m = re.search(r"id=([0-9a-f-]{36})", ln)
                if m:
                    cur = m.group(1)
                if re.search(r"\bK\d+\b", ln) and "TC-6601" in ln:
                    await call(session, "kicad_sch_delete_item", {"item_id": cur})

            print("【2】重放 3x5 按键矩阵")
            idx = 1
            for r in range(ROWS):
                for c in range(COLS):
                    x = X0 + c * COL_GAP
                    y = Y0 + r * ROW_GAP
                    await call(session, "kicad_sch_add_symbol",
                               {"lib_nickname": "keyboard-89_local",
                                "entry_name": "TC-6601-5-160G",
                                "x_mm": x, "y_mm": y, "reference": f"K{idx}", "value": ""})
                    idx += 1

            print("【3】用精确引脚坐标放 label")
            syms = _read_symbols()
            for ref in sorted(syms):
                if not re.match(r"K\d+", ref):
                    continue
                num = int(ref[1:])
                r = (num - 1) // COLS
                c = (num - 1) % COLS
                pins = syms[ref]["pins"]
                for pn, net in (("1", f"C{c+1}"), ("2", f"C{c+1}"),
                                ("3", f"R{r+1}"), ("4", f"R{r+1}")):
                    ix, iy = pins[pn]
                    await call(session, "kicad_sch_add_label",
                               {"label_type": "local", "text": net,
                                "x_mm": ix / MM, "y_mm": iy / MM})
            print("  已放 label")

            print("【4】PWR_FLAG 驱动电源网络")
            # 3V3: LDO 输出附近
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 66.04, "y_mm": 126, "reference": "PWR3"})
            # 0: LDO 地附近
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 53.34, "y_mm": 150, "reference": "PWR0"})
            # VBUS: USB 附近
            await call(session, "kicad_sch_add_symbol",
                       {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                        "x_mm": 53.34, "y_mm": 28, "reference": "PWRV"})
            # PWR_FLAG 引脚接同名网络 label
            syms2 = _read_symbols()
            for pref, net in (("PWR3", "3V3"), ("PWR0", "0"), ("PWRV", "VBUS")):
                if pref in syms2:
                    for pn, (ix, iy) in syms2[pref]["pins"].items():
                        await call(session, "kicad_sch_add_label",
                                   {"label_type": "local", "text": net,
                                    "x_mm": ix / MM, "y_mm": iy / MM})

            print("【5】USBC 未用引脚接 GND")
            j1 = syms2.get("J1", {}).get("pins", {})
            for pn in ("4", "5", "8", "9", "10"):  # CC1, DN2, DP2, SBU1, CC2
                if pn in j1:
                    ix, iy = j1[pn]
                    await call(session, "kicad_sch_add_label",
                               {"label_type": "local", "text": "0",
                                "x_mm": ix / MM, "y_mm": iy / MM})

            print("【6】保存")
            print(await call(session, "kicad_save_document", {}))


if __name__ == "__main__":
    asyncio.run(main())
