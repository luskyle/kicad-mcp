"""单回路串联电路 v2：引脚感知绘制（精确连到引脚 + 旋转元件）。

通过 MCP 工具绘制到 demos/simple_series/Simple_Series.kicad_sch。
- add_symbol 返回每个引脚的绝对坐标
- kicad_sch_connect 按引脚名连线（自动对齐 + 可控制走线路径）
- 灯泡旋转 90° 演示旋转后引脚/连线正确

用法: PYTHONPATH=src python tests/draw_series_v2.py
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

            print("【1】放置元件（含旋转演示）")
            out = await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "Device", "entry_name": "Battery_Cell",
                              "x_mm": 70.0, "y_mm": 80.0, "reference": "BAT1", "value": "9V"})
            print(out)
            out = await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "Switch", "entry_name": "SW_SPST",
                              "x_mm": 140.0, "y_mm": 80.0, "reference": "SW1", "value": "SPST"})
            print(out)
            # 灯泡旋转 90°（横放），验证旋转后引脚位置正确
            out = await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "Device", "entry_name": "Lamp",
                              "x_mm": 210.0, "y_mm": 80.0, "reference": "LAMP1",
                              "value": "12V", "orientation_degrees": 90})
            print(out)

            print("\n【2】查询引脚（验证旋转后坐标）")
            out = await call(session, "kicad_sch_get_symbol_pins", {"reference": "LAMP1"})
            print(out)

            print("\n【3】引脚感知连线（单回路）")
            # 电池-（上，pin2）→ 顶部轨道 → 开关 A（左）
            out = await call(session, "kicad_sch_connect",
                             {"ref_a": "BAT1", "pin_a": "2", "ref_b": "SW1", "pin_b": "1",
                              "via_y_mm": 55.0})
            print(out)
            # 开关 B（右）→ 灯泡 pin1（左，旋转后）——同 y，直接水平
            out = await call(session, "kicad_sch_connect",
                             {"ref_a": "SW1", "pin_a": "2", "ref_b": "LAMP1", "pin_b": "1"})
            print(out)
            # 灯泡 pin2（右，旋转后）→ 底部轨道 → 电池+（下，pin1）
            out = await call(session, "kicad_sch_connect",
                             {"ref_a": "LAMP1", "pin_a": "2", "ref_b": "BAT1", "pin_b": "1",
                              "via_y_mm": 105.0})
            print(out)

            print("\n【4】文本注释")
            for txt, x, y, h in [
                ("Single Series Circuit", 70, 140, 3.5),
                ("BAT1=9V | SW1=SPST | LAMP1=12V (rotated 90)", 70, 155, 2.5),
            ]:
                out = await call(session, "kicad_sch_add_text",
                                 {"text": txt, "x_mm": x, "y_mm": y, "height_mm": h})
                print(out)

            print("\n【5】保存")
            out = await call(session, "kicad_save_document", {})
            print(out)

            print("\n[PASS] 引脚感知的单回路电路绘制完成")


if __name__ == "__main__":
    asyncio.run(main())
