"""RC 充电电路 + SPICE 仿真验证（全横放布局，1.27mm 网格）。

电路: V1(DC 5V) ─ R1(1k) ─ C1(100u) ─ GND
       V1(-) ─ GND
仿真: .tran 1u 20m（瞬态 20ms），看 C1 充电曲线。

用法: PYTHONPATH=src python tests/draw_rc_circuit.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
sys.path.insert(0, SRC)

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402


async def call(session, name, args) -> str:
    res = await session.call_tool(name, args)
    return "\n".join(getattr(c, "text", str(c)) for c in res.content)


async def clear_sheet(session) -> None:
    """清空当前原理图（按 id 逐个删除）。"""
    out = await call(session, "kicad_sch_get_items", {"item_types": "text,symbol,line,label"})
    # KiCad UUID 是 8-4-4-4-12（带连字符），不是纯 32 位十六进制
    ids = re.findall(r"id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", out)
    if not ids:
        print("  原理图已空")
        return
    for i, iid in enumerate(ids, 1):
        await call(session, "kicad_sch_delete_item", {"item_id": iid})
    print(f"  已清空 {len(ids)} 个元素")


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("【0】当前应为空原理图（RC_Charge.kicad_sch）")
            await clear_sheet(session)

            print("\n【1】放置元件（全横放 y=76.2）")
            for lib, entry, x, ref, val, rot in [
                ("Simulation_SPICE", "VDC", 63.5, "V1", "5", 90),
                ("Device", "R", 127.0, "R1", "1k", 90),
                ("Device", "C", 190.5, "C1", "100u", 90),
            ]:
                print(await call(session, "kicad_sch_add_symbol",
                                 {"lib_nickname": lib, "entry_name": entry,
                                  "x_mm": x, "y_mm": 76.2, "reference": ref,
                                  "value": val, "orientation_degrees": rot}))
            # GND 符号（底部 rail）
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "power", "entry_name": "GND",
                              "x_mm": 63.5, "y_mm": 93.98, "reference": "GND1"}))
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "power", "entry_name": "GND",
                              "x_mm": 190.5, "y_mm": 93.98, "reference": "GND2"}))
            # Power Flag：声明 GND 网络由外部驱动，否则 ERC 报 Input Power 未驱动。
            # 注意：PWR_FLAG 的连线终点若与其它线在 GND pin 处重叠，KiCad 会合并
            # 导致 pin 被"埋"而不连接。放到 C1 侧独立位置，用 add_line 单独引线。
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "power", "entry_name": "PWR_FLAG",
                              "x_mm": 194.31, "y_mm": 93.98, "reference": "PWR1"}))

            print("\n【2】读回引脚")
            for ref in ("V1", "R1", "C1"):
                print(await call(session, "kicad_sch_get_symbol_pins", {"reference": ref}))

            print("\n【3】连线（引脚感知，底部 rail y=88.9）")
            # V1.pin1(+) -> R1.pin1（水平）
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "V1", "pin_a": "1", "ref_b": "R1", "pin_b": "1"}))
            # R1.pin2 -> C1.pin1（水平）
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "R1", "pin_a": "2", "ref_b": "C1", "pin_b": "1"}))
            # C1.pin2 -> 底部 rail -> GND2
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "C1", "pin_a": "2", "ref_b": "GND2", "pin_b": "1",
                              "via_y_mm": 88.9}))
            # V1.pin2(-) -> 底部 rail -> GND1
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "V1", "pin_a": "2", "ref_b": "GND1", "pin_b": "1",
                              "via_y_mm": 88.9}))
            # PWR_FLAG 单独引线到 C1 侧 rail（x=194.31，与 C1 竖线共点但不同段，无重叠）
            print(await call(session, "kicad_sch_add_line",
                             {"x1_mm": 194.31, "y1_mm": 93.98,
                              "x2_mm": 194.31, "y2_mm": 88.9, "layer": "wire"}))

            print("\n【4】网络标签（VIN/OUT）+ SPICE 指令")
            print(await call(session, "kicad_sch_add_label",
                             {"label_type": "local", "text": "VIN",
                              "x_mm": 95.25, "y_mm": 76.2}))
            print(await call(session, "kicad_sch_add_label",
                             {"label_type": "local", "text": "OUT",
                              "x_mm": 158.75, "y_mm": 76.2}))
            for txt, x, y, h in [
                ("RC Charging Circuit: V1=5V DC, R1=1k, C1=100u", 63.5, 107.95, 3.5),
                (".tran 1u 20m", 63.5, 114.3, 2.5),
                ("SPICE: watch V(out) charge to 5V with tau=100ms", 63.5, 119.38, 2.0),
            ]:
                print(await call(session, "kicad_sch_add_text",
                                 {"text": txt, "x_mm": x, "y_mm": y, "height_mm": h}))

            print("\n【5】保存 + ERC（当前文档=RC_Charge.kicad_sch）")
            print(await call(session, "kicad_save_document", {}))
            print(await call(session, "kicad_sch_erc", {}))


if __name__ == "__main__":
    asyncio.run(main())
