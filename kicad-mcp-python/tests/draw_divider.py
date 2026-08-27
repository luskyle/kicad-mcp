"""简单电阻分压电路（无仿真指令文本），用于验证自动仿真类型推荐/注入。

V1(5V) ─ R1(1k) ─┬─ R2(2k) ─ 0(GND)
                 └─ OUT
用法: PYTHONPATH=src python tests/draw_divider.py
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


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("【1】清空")
            out = await call(session, "kicad_sch_get_items",
                             {"item_types": "text,symbol,line,label"})
            ids = re.findall(r"id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", out)
            for iid in ids:
                await call(session, "kicad_sch_delete_item", {"item_id": iid})
            print(f"  清空 {len(ids)}")

            print("【2】放置（全横放 y=76.2）")
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "Simulation_SPICE", "entry_name": "VDC",
                              "x_mm": 63.5, "y_mm": 76.2, "reference": "V1",
                              "value": "5", "orientation_degrees": 90}))
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "Device", "entry_name": "R",
                              "x_mm": 127.0, "y_mm": 76.2, "reference": "R1",
                              "value": "1k", "orientation_degrees": 90}))
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "Device", "entry_name": "R",
                              "x_mm": 190.5, "y_mm": 76.2, "reference": "R2",
                              "value": "2k", "orientation_degrees": 90}))

            print("【3】连线")
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "V1", "pin_a": "1", "ref_b": "R1", "pin_b": "1"}))
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "R1", "pin_a": "2", "ref_b": "R2", "pin_b": "1"}))
            print(await call(session, "kicad_sch_add_line",
                             {"x1_mm": 194.31, "y1_mm": 76.2, "x2_mm": 194.31, "y2_mm": 88.9}))
            print(await call(session, "kicad_sch_add_line",
                             {"x1_mm": 68.58, "y1_mm": 76.2, "x2_mm": 68.58, "y2_mm": 88.9}))

            print("【4】标签 + 标题（无 .tran 指令！）")
            print(await call(session, "kicad_sch_add_label",
                             {"label_type": "local", "text": "VIN", "x_mm": 95.25, "y_mm": 76.2}))
            print(await call(session, "kicad_sch_add_label",
                             {"label_type": "local", "text": "OUT", "x_mm": 158.75, "y_mm": 76.2}))
            print(await call(session, "kicad_sch_add_label",
                             {"label_type": "local", "text": "0", "x_mm": 68.58, "y_mm": 88.9}))
            print(await call(session, "kicad_sch_add_label",
                             {"label_type": "local", "text": "0", "x_mm": 194.31, "y_mm": 88.9}))
            print(await call(session, "kicad_sch_add_text",
                             {"text": "Voltage Divider: V1=5V, R1=1k, R2=2k (no directive)",
                              "x_mm": 63.5, "y_mm": 107.95, "height_mm": 3.5}))

            print("【5】保存 + ERC")
            print(await call(session, "kicad_save_document", {}))
            print(await call(session, "kicad_sch_erc", {}))


if __name__ == "__main__":
    asyncio.run(main())
