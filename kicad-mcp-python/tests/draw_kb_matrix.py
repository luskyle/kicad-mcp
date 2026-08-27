"""键盘布局原理图：画 3x5 按键矩阵（TC-6601 按键 + 行列 label 网络）。

用法: PYTHONPATH=src python tests/draw_kb_matrix.py
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


async def call(session, name, args) -> str:
    res = await session.call_tool(name, args)
    return "\n".join(getattr(c, "text", str(c)) for c in res.content)


ROWS = 3
COLS = 5
X0, Y0 = 125.0, 215.0
COL_GAP, ROW_GAP = 15.0, 15.0


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("【0】删除临时按键 K0")
            out = await call(session, "kicad_sch_get_items", {"item_types": "symbol"})
            cur = None
            for ln in out.splitlines():
                m = re.search(r"id=([0-9a-f-]{36})", ln)
                if m:
                    cur = m.group(1)
                if "K0" in ln:
                    await call(session, "kicad_sch_delete_item", {"item_id": cur})

            print("【1】放置 3x5 按键矩阵")
            idx = 1
            for r in range(ROWS):
                for c in range(COLS):
                    x = X0 + c * COL_GAP
                    y = Y0 + r * ROW_GAP
                    ref = f"K{idx}"
                    await call(session, "kicad_sch_add_symbol",
                               {"lib_nickname": "keyboard-89_local",
                                "entry_name": "TC-6601-5-160G",
                                "x_mm": x, "y_mm": y, "reference": ref, "value": ""})
                    # pin1,2 -> 列线 C{c+1}；pin3,4 -> 行线 R{r+1}
                    for pn, net in (("1", f"C{c+1}"), ("2", f"C{c+1}"),
                                    ("3", f"R{r+1}"), ("4", f"R{r+1}")):
                        px = x - 6.35 if pn in ("1", "2") else x + 6.35
                        py = y - 1.75 if pn in ("1", "3") else y + 1.75
                        await call(session, "kicad_sch_add_label",
                                   {"label_type": "local", "text": net,
                                    "x_mm": px, "y_mm": py})
                    idx += 1
            print(f"  放置 {idx-1} 个按键")

            print("【2】加注释文本")
            await call(session, "kicad_sch_add_text",
                       {"text": "键盘矩阵 (示意 3x5, 完整 5x22 见 keyboard-89.sch)",
                        "x_mm": X0, "y_mm": Y0 - 12, "height_mm": 3.5})
            await call(session, "kicad_sch_add_text",
                       {"text": "每键需串联 1N4148W 二极管 (阳极接行, 阴极接列) 防串扰",
                        "x_mm": X0, "y_mm": Y0 + ROWS * ROW_GAP + 5, "height_mm": 3.5})
            await call(session, "kicad_sch_add_text",
                       {"text": "行列接 RP2040 GPIO: R1-3, C1-5",
                        "x_mm": X0, "y_mm": Y0 + ROWS * ROW_GAP + 10, "height_mm": 3.5})

            print("【3】保存")
            print(await call(session, "kicad_save_document", {}))


if __name__ == "__main__":
    asyncio.run(main())
