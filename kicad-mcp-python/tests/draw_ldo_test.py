"""端到端测试 v2：放置自定义元件（L78L05）+ 完整连线 + PWR_FLAG + ERC。

电路: V1(8V) ─ L78L05(IN) ─(OUT)→ VOUT
      L78L05(GND) ─ 0 网络（PWR_FLAG 驱动，满足 ERC）
用法: PYTHONPATH=src python tests/draw_ldo_test.py
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

            print("【2】放置")
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "Simulation_SPICE", "entry_name": "VDC",
                              "x_mm": 63.5, "y_mm": 76.2, "reference": "V1",
                              "value": "8"}))
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "divider_local", "entry_name": "L78L05",
                              "x_mm": 139.7, "y_mm": 76.2, "reference": "U1", "value": "L78L05"}))
            # PWR_FLAG：驱动 U1 的 GND(power_in) 网络，满足 ERC（GND 在底部，PWR_FLAG 放下方）
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                              "x_mm": 139.7, "y_mm": 88.9, "reference": "PWR1"}))

            print("【3】U1 引脚")
            print(await call(session, "kicad_sch_get_symbol_pins", {"reference": "U1"}))

            print("【4】连线")
            # V1 默认方向: pin1(+)=(63.5,71.12) 上, pin2(-)=(63.5,81.28) 下
            # V1.pin1(+) -> 向上 + label VIN（与 U1 左侧 VIN label 同名网络）
            print(await call(session, "kicad_sch_add_line",
                             {"x1_mm": 63.5, "y1_mm": 71.12, "x2_mm": 63.5, "y2_mm": 66.04}))
            # V1.pin2(-) -> 向下 + label 0（GND 网络）
            print(await call(session, "kicad_sch_add_line",
                             {"x1_mm": 63.5, "y1_mm": 81.28, "x2_mm": 63.5, "y2_mm": 88.9}))
            # U1.pin1(IN) -> 向左 + label VIN（与 V1 上方 VIN label 同名）
            print(await call(session, "kicad_sch_add_line",
                             {"x1_mm": 133.35, "y1_mm": 76.2, "x2_mm": 129.54, "y2_mm": 76.2}))
            # U1.pin2(GND, 顶) -> PWR1（GND 网络，PWR_FLAG 驱动）
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "U1", "pin_a": "2", "ref_b": "PWR1", "pin_b": "1"}))
            # U1.pin3(OUT) -> 右方 VOUT（终点在 1.27mm 网格 152.4=120*1.27）
            print(await call(session, "kicad_sch_add_line",
                             {"x1_mm": 146.05, "y1_mm": 76.2, "x2_mm": 152.4, "y2_mm": 76.2}))

            print("【5】标签")
            print(await call(session, "kicad_sch_add_label",
                             {"label_type": "local", "text": "VIN", "x_mm": 63.5, "y_mm": 66.04}))
            print(await call(session, "kicad_sch_add_label",
                             {"label_type": "local", "text": "VIN", "x_mm": 129.54, "y_mm": 76.2}))
            print(await call(session, "kicad_sch_add_label",
                             {"label_type": "local", "text": "VOUT", "x_mm": 152.4, "y_mm": 76.2}))
            print(await call(session, "kicad_sch_add_label",
                             {"label_type": "local", "text": "0", "x_mm": 139.7, "y_mm": 85.09}))
            print(await call(session, "kicad_sch_add_label",
                             {"label_type": "local", "text": "0", "x_mm": 63.5, "y_mm": 88.9}))
            print(await call(session, "kicad_sch_add_text",
                             {"text": "LDO L78L05 (custom symbol from private lib)", "x_mm": 60, "y_mm": 110, "height_mm": 3.5}))

            print("【6】保存 + ERC")
            print(await call(session, "kicad_save_document", {}))
            print(await call(session, "kicad_sch_erc", {}))


if __name__ == "__main__":
    asyncio.run(main())
