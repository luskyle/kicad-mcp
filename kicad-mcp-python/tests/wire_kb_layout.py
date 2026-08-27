"""键盘布局原理图：连线电源/USB/SPI/晶振/调试网络。

用法: PYTHONPATH=src python tests/wire_kb_layout.py
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


# (网络名, [(x, y), ...]) 每个网络的所有 label 位置（引脚端点）
NETWORKS = {
    "3V3": [
        (66.04, 137.95),    # LDO.VOUT
        (109.22, 175.26),   # C1.1
        # RP2040 顶部电源引脚
        (224.39, 68.66), (219.39, 68.66), (214.39, 68.66), (209.39, 68.66),
        (204.39, 68.66), (199.39, 68.66), (194.39, 68.66), (189.39, 68.66),
        (184.39, 68.66), (179.39, 68.66), (174.39, 68.66),
        (349.25, 183.84),   # J2.4
        (356.87, 59.86),    # U3.VCC
        (344.17, 56.36),    # U3.WP#
        (356.87, 56.36),    # U3.HOLD#
        (201.89, 152.32),   # U1.RUN 上拉
    ],
    "VBUS": [
        (53.34, 38.86),     # USBC.VBUS 2
        (53.34, 70.36),     # USBC.VBUS 11
        (53.34, 137.95),    # LDO.VIN
    ],
    "0": [
        (53.34, 35.36),     # USBC.GND 1
        (53.34, 73.86),     # USBC.GND 12
        (53.34, 42.36),     # USBC.SBU2(未用,置GND也可省略)
        (66.04, 35.36),     # USBC.SHELL 13
        (66.04, 38.86),     # USBC.SHELL 14
        (53.34, 141.45),    # LDO.ADJ/GND
        (121.92, 175.26),   # C1.2
        (216.89, 152.32),   # U1.GND 57
        (344.17, 59.86),    # U3.VSS
        (349.25, 180.34),   # J2.3
    ],
    "USB_DP": [
        (53.34, 52.86),     # USBC.DP1
        (229.43, 147.24),   # U1.USB_DP 47
    ],
    "USB_DM": [
        (53.34, 56.36),     # USBC.DN1
        (229.43, 143.74),   # U1.USB_DM 46
    ],
    "FLASH_CS": [
        (229.43, 140.24),   # U1.QSPI_CSn
        (344.17, 49.36),    # U3.CS#
    ],
    "FLASH_SCLK": [
        (229.43, 126.24),   # U1.QSPI_SCLK
        (356.87, 52.86),    # U3.SCLK
    ],
    "FLASH_SD0": [
        (229.43, 129.74),   # U1.QSPI_SD0
        (356.87, 49.36),    # U3.SI
    ],
    "FLASH_SD1": [
        (229.43, 136.74),   # U1.QSPI_SD1
        (344.17, 52.86),    # U3.SO
    ],
    "SWCLK": [
        (196.89, 152.32),   # U1.SWCLK
        (349.25, 173.34),   # J2.1
    ],
    "SWD": [
        (191.89, 152.32),   # U1.SWD
        (349.25, 176.84),   # J2.2
    ],
    "XIN": [
        (186.89, 152.32),   # U1.XIN 20
    ],
    "XOUT": [
        (181.89, 152.32),   # U1.XOUT 21
    ],
}


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("【1】电源/USB/SPI/调试 网络 label")
            for net, pts in NETWORKS.items():
                for x, y in pts:
                    r = await call(session, "kicad_sch_add_label",
                                   {"label_type": "local", "text": net, "x_mm": x, "y_mm": y})
                    if "创建" not in r:
                        print(f"  {net} @({x},{y}): {r[:80]}")

            print("【2】删除旧晶振 Y1 并就近重放")
            out = await call(session, "kicad_sch_get_items", {"item_types": "symbol"})
            cur = None
            target = None
            for ln in out.splitlines():
                m = re.search(r"id=([0-9a-f-]{36})", ln)
                if m:
                    cur = m.group(1)
                if "Y1" in ln and "YXC" in ln:
                    target = cur
            if target:
                print(await call(session, "kicad_sch_delete_item", {"item_id": target}))
            # 晶振重放到 RP2040 XIN/XOUT 下方
            print(await call(session, "kicad_sch_add_symbol",
                             {"lib_nickname": "keyboard-89_local", "entry_name": "YXC",
                              "x_mm": 184, "y_mm": 168, "reference": "Y1", "value": "12MHz"}))

            print("【3】晶振连线 (OSC1->XIN, OSC2->XOUT)")
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "Y1", "pin_a": "1", "ref_b": "U1", "pin_b": "20"}))
            print(await call(session, "kicad_sch_connect",
                             {"ref_a": "Y1", "pin_a": "3", "ref_b": "U1", "pin_b": "21"}))
            # Y1 GND 接地
            out2 = await call(session, "kicad_sch_get_symbol_pins", {"reference": "Y1"})
            for ln in out2.splitlines():
                m = re.search(r"引脚 (\d+) = \(([\d.]+), ([\d.]+)\)", ln)
                if m and m.group(1) in ("2", "4"):
                    gx, gy = float(m.group(2)), float(m.group(3))
                    print(await call(session, "kicad_sch_add_label",
                                     {"label_type": "local", "text": "0", "x_mm": gx, "y_mm": gy}))

            print("【4】保存")
            print(await call(session, "kicad_save_document", {}))


if __name__ == "__main__":
    asyncio.run(main())
