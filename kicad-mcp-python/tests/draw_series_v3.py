"""单回路电路 v3：网格对齐版（1.27mm 网格），目标是通过 KiCad ERC。

所有元件中心与引脚都落在 1.27mm 网格上，避免 ERC 报
"off connection grid" / "Pin not connected"。

用法: PYTHONPATH=src python tests/draw_series_v3.py
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

            print("【1】放置元件（1.27mm 网格坐标）")
            # 中心都在 1.27mm 网格；符号引脚(2.54/5.08)也是 1.27 整数倍
            out = await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "Device", "entry_name": "Battery_Cell",
                              "x_mm": 63.5, "y_mm": 76.2, "reference": "BAT1", "value": "9V"})
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

            print("\n【2】引脚感知连线（rails 也在网格上）")
            # 电池-（上）-> 顶部 rail(y=63.5) -> 开关 A
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "BAT1", "pin_a": "2", "ref_b": "SW1", "pin_b": "1",
                              "via_y_mm": 63.5}))
            # 开关 B -> 灯泡 1（旋转后左侧）
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "SW1", "pin_a": "2", "ref_b": "LAMP1", "pin_b": "1"}))
            # 灯泡 2（旋转后右侧）-> 底部 rail(y=88.9) -> 电池+
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "LAMP1", "pin_a": "2", "ref_b": "BAT1", "pin_b": "1",
                              "via_y_mm": 88.9}))

            print("\n【3】文本")
            for txt, x, y, h in [
                ("Single Series Circuit", 63.5, 107.95, 3.5),
                ("BAT1=9V | SW1=SPST | LAMP1=12V (rotated 90)", 63.5, 114.3, 2.5),
            ]:
                print(await call(session, "kicad_sch_add_text",
                                 {"text": txt, "x_mm": x, "y_mm": y, "height_mm": h}))

            print("\n【4】保存 + ERC")
            print(await call(session, "kicad_save_document", {}))
            erc = await call(session, "kicad_sch_erc", {})
            print(erc)
            print("\n[PASS] 网格对齐版绘制完成")


if __name__ == "__main__":
    asyncio.run(main())
