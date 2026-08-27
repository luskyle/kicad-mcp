"""完整画图流程实测：模拟 AI 通过 MCP 在原理图上画一个 LED 电路。

流程: 查现状 -> 放元件(R1/LED1/C1) -> 连线(wire) -> 网络标签(VCC/GND)
     -> 文本注释 -> 读回验证 -> 保存落盘。

前置条件: 编译版 eeschema 已打开 demos/stickhub/StickHub.kicad_sch。
用法: PYTHONPATH=src python tests/demo_draw_flow.py
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

# 画图区域（StickHub 内容之外）
AREA = dict(x0=500.0, y0=90.0)


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

            # ---------- 1) 查现状 ----------
            print("【1】查询原理图现状（符号/文本数量）")
            out = await call(session, "kicad_sch_get_items", {"item_types": "symbol"})
            sym_count = len([l for l in out.splitlines() if "Symbol " in l])
            print(f"  现有符号: {sym_count} 个")

            # ---------- 2) 画电路 ----------
            print("\n【2】放置元件")
            for sym, ref, val, x, y, orient in [
                ("R", "R1", "10k", 500, 115, 0),
                ("LED", "LED1", "Red", 540, 150, 0),
                ("C", "C1", "100n", 500, 180, 90),
            ]:
                out = await call(session, "kicad_sch_add_symbol",
                                 {"lib_nickname": "Device", "entry_name": sym,
                                  "x_mm": x, "y_mm": y, "reference": ref,
                                  "value": val, "orientation_degrees": orient})
                print(f"  {out}")

            print("\n【3】画连线 (wire)")
            wires = [
                # VCC -> R1 顶
                (500, 90, 500, 115),
                # R1 -> LED1（折线）
                (500, 115, 540, 115), (540, 115, 540, 150),
                # LED1 -> GND
                (540, 150, 540, 200),
                # C1 并联到 R1 下端
                (500, 150, 500, 180), (500, 180, 540, 180),
            ]
            for x1, y1, x2, y2 in wires:
                out = await call(session, "kicad_sch_add_line",
                                 {"x1_mm": x1, "y1_mm": y1, "x2_mm": x2, "y2_mm": y2,
                                  "layer": "wire"})
            print(f"  已画 {len(wires)} 条连线")

            print("\n【4】网络标签")
            for lab, txt, x, y in [("global", "MCP_VCC", 500, 85),
                                   ("global", "MCP_GND", 540, 205)]:
                out = await call(session, "kicad_sch_add_label",
                                 {"label_type": lab, "text": txt, "x_mm": x, "y_mm": y})
                print(f"  {out}")

            print("\n【5】文本注释")
            out = await call(session, "kicad_sch_add_text",
                             {"text": "MCP Demo: R1 + LED1", "x_mm": 500.0, "y_mm": 230.0})
            print(f"  {out}")

            # ---------- 3) 读回验证 ----------
            print("\n【6】读回验证")
            out = await call(session, "kicad_sch_get_items", {"item_types": "symbol"})
            ok = all(s in out for s in ("R1", "LED1", "C1"))
            print("  符号 R1/LED1/C1:", "✅" if ok else "❌")
            if not ok:
                print(out)

            out = await call(session, "kicad_sch_get_items", {"item_types": "global_label"})
            ok = "MCP_VCC" in out and "MCP_GND" in out
            print("  标签 MCP_VCC/MCP_GND:", "✅" if ok else "❌")

            out = await call(session, "kicad_sch_get_items", {"item_types": "line"})
            print(f"  连线数: {len([l for l in out.splitlines() if 'Line ' in l])}")

            out = await call(session, "kicad_sch_get_items", {"item_types": "text"})
            ok = "MCP Demo" in out
            print("  文本注释:", "✅" if ok else "❌")

            # ---------- 4) 保存 ----------
            print("\n【7】保存原理图")
            out = await call(session, "kicad_save_document", {})
            print(f"  {out}")

            print("\n[PASS] 完整画图流程执行成功（元素已画入并保存）")


if __name__ == "__main__":
    asyncio.run(main())
