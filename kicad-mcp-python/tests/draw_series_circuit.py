"""画单回路串联电路原理图（电池电源 + SPST 开关 + 灯泡负载）。

通过 MCP 工具绘制到 demos/simple_series/Simple_Series.kicad_sch。
用法: PYTHONPATH=src python tests/draw_series_circuit.py
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

            print("【1】放置元件（电源/开关/负载）")
            parts = [
                # 电源: Device 电池（A4 正式区域内居中）
                ("Device", "Battery_Cell", "BAT1", "9V", 70, 80, 0),
                # 控制开关: Switch 库 SPST
                ("Switch", "SW_SPST", "SW1", "SPST", 140, 80, 0),
                # 负载: Device 灯泡
                ("Device", "Lamp", "LAMP1", "12V", 210, 80, 0),
            ]
            for lib, name, ref, val, x, y, orient in parts:
                out = await call(session, "kicad_sch_add_symbol",
                                 {"lib_nickname": lib, "entry_name": name,
                                  "x_mm": x, "y_mm": y, "reference": ref,
                                  "value": val, "orientation_degrees": orient})
                print(f"  {out}")

            print("\n【2】画连线（单回路）")
            wires = [
                # 电池+ -> 顶线 -> 开关引脚1
                (70, 72, 70, 55),
                (70, 55, 138, 55),
                (138, 55, 138, 80),
                # 开关引脚2 -> 灯泡引脚1
                (142, 80, 208, 80),
                # 灯泡引脚2 -> 底线 -> 电池-（回到负极，闭合回路）
                (212, 80, 212, 105),
                (212, 105, 70, 105),
                (70, 105, 70, 88),
            ]
            for x1, y1, x2, y2 in wires:
                await call(session, "kicad_sch_add_line",
                           {"x1_mm": x1, "y1_mm": y1, "x2_mm": x2, "y2_mm": y2,
                            "layer": "wire"})
            print(f"  已画 {len(wires)} 条连线")

            print("\n【3】文本注释")
            for txt, x, y, h in [
                ("Single Series Circuit", 70, 135, 3.5),
                ("BAT1 = 9V battery | SW1 = SPST switch | LAMP1 = load", 70, 150, 2.5),
            ]:
                out = await call(session, "kicad_sch_add_text",
                                 {"text": txt, "x_mm": x, "y_mm": y, "height_mm": h})
                print(f"  {out}")

            print("\n【4】读回验证")
            out = await call(session, "kicad_sch_get_items", {"item_types": "symbol"})
            for ref in ("BAT1", "SW1", "LAMP1"):
                print(f"  {ref}: {'✅' if ref in out else '❌'}")
            out = await call(session, "kicad_sch_get_items", {"item_types": "line"})
            n = len([l for l in out.splitlines() if "Line " in l])
            print(f"  连线数: {n}")

            print("\n【5】保存")
            out = await call(session, "kicad_save_document", {})
            print(f"  {out}")

            print("\n[PASS] 单回路串联电路已绘制并保存")


if __name__ == "__main__":
    asyncio.run(main())
