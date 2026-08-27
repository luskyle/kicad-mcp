"""单回路电路 v4：全部元件横放，引脚左右，避免共线 wire 被合并导致 ERC 未连接。

关键修复：竖直电池的上下引脚连线会在同一竖线上重叠，KiCad 合并共线 wire
后把引脚"埋"在线中间 → ERC 报 Pin not connected。把电池也旋转 90° 横放，
引脚在左右，连线各自独立。

用法: PYTHONPATH=src python tests/draw_series_v4.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
sys.path.insert(0, SRC)

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import (  # noqa: E402
    StdioServerParameters,
    stdio_client,
)


async def call(session, name, args) -> str:
    res = await session.call_tool(name, args)
    return "\n".join(getattr(c, "text", str(c)) for c in res.content)


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("【1】放置元件（全横放，1.27mm 网格）")
            # 电池横放(旋转90)：引脚在左右，避免竖线贯穿
            out = await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "Device", "entry_name": "Battery_Cell",
                              "x_mm": 63.5, "y_mm": 76.2, "reference": "BAT1",
                              "value": "9V", "orientation_degrees": 90})
            print(out)
            out = await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "Switch", "entry_name": "SW_SPST",
                              "x_mm": 139.7, "y_mm": 76.2, "reference": "SW1", "value": "SPST"})
            print(out)
            out = await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "Device", "entry_name": "Lamp",
                              "x_mm": 203.2, "y_mm": 76.2, "reference": "LAMP1",
                              "value": "12V", "orientation_degrees": 90})
            print(out)

            print("\n【2】读回 KiCad 引脚位置")
            for ref in ("BAT1", "SW1", "LAMP1"):
                print(await call(session, "kicad_sch_get_symbol_pins", {"reference": ref}))

            print("\n【3】引脚感知连线（rails 网格对齐）")
            # BAT1.pin1 -> 顶部 rail(y=63.5) -> SW1.A
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "BAT1", "pin_a": "1", "ref_b": "SW1", "pin_b": "1",
                              "via_y_mm": 63.5}))
            # SW1.B -> LAMP1.pin1（同 y，水平直线）
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "SW1", "pin_a": "2", "ref_b": "LAMP1", "pin_b": "1"}))
            # LAMP1.pin2 -> 底部 rail(y=88.9) -> BAT1.pin2
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "LAMP1", "pin_a": "2", "ref_b": "BAT1", "pin_b": "2",
                              "via_y_mm": 88.9}))

            print("\n【4】文本 + 保存 + ERC")
            for txt, x, y, h in [
                ("Single Series Circuit", 63.5, 107.95, 3.5),
                ("BAT1=9V | SW1=SPST | LAMP1=12V (all horizontal)", 63.5, 114.3, 2.5),
            ]:
                print(await call(session, "kicad_sch_add_text",
                                 {"text": txt, "x_mm": x, "y_mm": y, "height_mm": h}))
            print(await call(session, "kicad_save_document", {}))
            print(await call(session, "kicad_sch_erc", {}))
            print("\n[PASS] 完成")


if __name__ == "__main__":
    asyncio.run(main())
