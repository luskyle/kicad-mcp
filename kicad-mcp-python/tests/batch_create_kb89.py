"""批量封装 keyboard-89 目录元件手册中的元件为自定义符号。

引脚定义复用用户已有 private_lib.kicad_sym（已核对手册），但用 MCP 重新
封装到 keyboard-89_local（.kicad_symdir，带正确的引脚电气类型）。
用法: PYTHONPATH=src python tests/batch_create_kb89.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
sys.path.insert(0, SRC)

from kicad_mcp.tools.symbol_lib import kicad_sch_create_custom_symbol

SCH = "/home/luskyle/桌面/keyboard-89/keyboard-89.kicad_sch"

# 每个元件: (name, description, footprint, layout, pins)
# pin: (number, name, type, side)
COMPONENTS = [
    {
        "name": "C-100nF",
        "description": "100nF 去耦电容 (0402)",
        "footprint": "Capacitor_SMD:C_0402_1005Metric",
        "layout": {"left_spacing": 2.54, "pin_spacing": 3.5},
        "pins": [("1", "1", "passive", "left"), ("2", "2", "passive", "right")],
    },
    {
        "name": "LDO",
        "description": "低压差线性稳压器 (LDO)",
        "footprint": "",
        "layout": {"left_spacing": 2.54, "pin_spacing": 3.81},
        "pins": [
            ("3", "VIN", "power_in", "left"),
            ("1", "ADJ/GND", "input", "left"),
            ("2", "VOUT", "power_out", "right"),
        ],
    },
    {
        "name": "GD25Q16E",
        "description": "GigaDevice GD25Q16E 16Mbit SPI NOR Flash (SOIC-8)",
        "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        "layout": {"left_spacing": 2.54, "pin_spacing": 3.81},
        "pins": [
            ("1", "CS#", "input", "left"),
            ("2", "SO", "output", "left"),
            ("3", "WP#", "input", "left"),
            ("4", "VSS", "power_in", "left"),
            ("5", "SI", "input", "right"),
            ("6", "SCLK", "input", "right"),
            ("7", "HOLD#", "input", "right"),
            ("8", "VCC", "power_in", "right"),
        ],
    },
    {
        "name": "TC-6601-5-160G",
        "description": "6x6 轻触按键开关 (TC-6601, 160gf)",
        "footprint": "",
        "layout": {"left_spacing": 2.54, "pin_spacing": 3.81},
        "pins": [
            ("1", "1", "passive", "left"),
            ("2", "2", "passive", "left"),
            ("3", "3", "passive", "right"),
            ("4", "4", "passive", "right"),
        ],
    },
    {
        "name": "USBC",
        "description": "USB Type-C 连接器 16P (C2765186)",
        "footprint": "",
        "layout": {"left_spacing": 2.54, "pin_spacing": 3.81},
        "pins": [
            ("1", "GND", "power_in", "left"),
            ("2", "VBUS", "power_in", "left"),
            ("3", "SBU2", "passive", "left"),
            ("4", "CC1", "bidirectional", "left"),
            ("5", "DN2", "bidirectional", "left"),
            ("6", "DP1", "bidirectional", "left"),
            ("7", "DN1", "bidirectional", "left"),
            ("8", "DP2", "bidirectional", "left"),
            ("9", "SBU1", "passive", "left"),
            ("10", "CC2", "bidirectional", "left"),
            ("11", "VBUS", "power_in", "left"),
            ("12", "GND", "power_in", "left"),
            ("13", "SHELL", "passive", "right"),
            ("14", "SHELL", "passive", "right"),
        ],
    },
    {
        "name": "USBA",
        "description": "USB A 型连接器 (U217-041N-4BV81)",
        "footprint": "",
        "layout": {"left_spacing": 2.54, "pin_spacing": 3.81},
        "pins": [
            ("1", "VCC", "power_in", "left"),
            ("2", "D-", "bidirectional", "left"),
            ("3", "D+", "bidirectional", "left"),
            ("4", "GND", "power_in", "left"),
            ("5", "SHIELD", "passive", "right"),
            ("6", "SHIELD", "passive", "right"),
        ],
    },
    {
        "name": "YXC",
        "description": "12MHz 无源晶振 (3215 4pin, X322512MSB4SI)",
        "footprint": "Crystal_SMD:3215_4Pin_3.2x1.5mm",
        "layout": {"left_spacing": 2.54, "pin_spacing": 3.81},
        "pins": [
            ("1", "OSC1", "passive", "left"),
            ("4", "GND", "power_in", "left"),
            ("3", "OSC2", "passive", "right"),
            ("2", "GND", "power_in", "right"),
        ],
    },
    {
        "name": "PIN-5P",
        "description": "5 针排针连接器",
        "footprint": "Connector_PinHeader:PinHeader_1x05_P2.54mm_Vertical",
        "layout": {"left_spacing": 2.54, "pin_spacing": 3.81},
        "pins": [
            ("1", "1", "passive", "left"),
            ("2", "2", "passive", "left"),
            ("3", "3", "passive", "left"),
            ("4", "4", "passive", "left"),
            ("5", "5", "passive", "left"),
        ],
    },
]


async def main() -> None:
    for c in COMPONENTS:
        spec = {
            "name": c["name"],
            "reference": "U" if c["name"] not in ("C-100nF", "TC-6601-5-160G", "YXC") else "U",
            "description": c["description"],
            "footprint": c["footprint"],
            "layout": c["layout"],
            "pins": [{"number": n, "name": nm, "type": t, "side": s}
                     for n, nm, t, s in c["pins"]],
        }
        print(await asyncio.to_thread(
            kicad_sch_create_custom_symbol, json.dumps(spec, ensure_ascii=False),
            "", SCH, True))
        print("---")


if __name__ == "__main__":
    asyncio.run(main())
