"""从 RP2040 数据手册提取的引脚信息生成自定义元件符号。

数据来源: /home/luskyle/桌面/keyboard-89/RP2040_DATASHEET.pdf 的 5.2.2.2 Pin List
(Table 620-626)。RP2040 为 56 引脚 QFN-56。

布局:
  左: GPIO0-15 (pin 2-9,11-18)
  右: GPIO16-29 (27-32,34-41) + QSPI (51-56) + USB (46,47)
  顶: IOVDD/DVDD/VREG_VIN/USB_VDD/ADC_AVDD (1,10,22,23,33,42,43,44,48,49,50)
  底: GND(57 pad)/VREG_VOUT/TESTEN/RUN/SWCLK/SWD/XIN/XOUT
用法: PYTHONPATH=src python tests/create_rp2040.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
sys.path.insert(0, SRC)

from kicad_mcp.tools.symbol_lib import kicad_sch_create_custom_symbol

SCH = "/home/luskyle/桌面/keyboard-89/keyboard-89.kicad_sch"

# 引脚定义: (引脚号, 名称, 类型, side)
# GPIO bank 0: pin2-9 -> GPIO0-7, pin11-18 -> GPIO8-15（左侧）
#              pin27-32 -> GPIO16-21, pin34-41 -> GPIO22-29（右侧）
PINS = [
    # 左侧 GPIO0-15
    ("2", "GPIO0", "bidirectional", "left"),
    ("3", "GPIO1", "bidirectional", "left"),
    ("4", "GPIO2", "bidirectional", "left"),
    ("5", "GPIO3", "bidirectional", "left"),
    ("6", "GPIO4", "bidirectional", "left"),
    ("7", "GPIO5", "bidirectional", "left"),
    ("8", "GPIO6", "bidirectional", "left"),
    ("9", "GPIO7", "bidirectional", "left"),
    ("11", "GPIO8", "bidirectional", "left"),
    ("12", "GPIO9", "bidirectional", "left"),
    ("13", "GPIO10", "bidirectional", "left"),
    ("14", "GPIO11", "bidirectional", "left"),
    ("15", "GPIO12", "bidirectional", "left"),
    ("16", "GPIO13", "bidirectional", "left"),
    ("17", "GPIO14", "bidirectional", "left"),
    ("18", "GPIO15", "bidirectional", "left"),
    # 右侧 GPIO16-29
    ("27", "GPIO16", "bidirectional", "right"),
    ("28", "GPIO17", "bidirectional", "right"),
    ("29", "GPIO18", "bidirectional", "right"),
    ("30", "GPIO19", "bidirectional", "right"),
    ("31", "GPIO20", "bidirectional", "right"),
    ("32", "GPIO21", "bidirectional", "right"),
    ("34", "GPIO22", "bidirectional", "right"),
    ("35", "GPIO23", "bidirectional", "right"),
    ("36", "GPIO24", "bidirectional", "right"),
    ("37", "GPIO25", "bidirectional", "right"),
    ("38", "GPIO26", "bidirectional", "right"),
    ("39", "GPIO27", "bidirectional", "right"),
    ("40", "GPIO28", "bidirectional", "right"),
    ("41", "GPIO29", "bidirectional", "right"),
    # 右侧 QSPI flash 接口 + USB（与 GPIO16-29 同侧）
    ("51", "QSPI_SD3", "bidirectional", "right"),
    ("52", "QSPI_SCLK", "bidirectional", "right"),
    ("53", "QSPI_SD0", "bidirectional", "right"),
    ("54", "QSPI_SD2", "bidirectional", "right"),
    ("55", "QSPI_SD1", "bidirectional", "right"),
    ("56", "QSPI_CSn", "bidirectional", "right"),
    ("46", "USB_DM", "bidirectional", "right"),
    ("47", "USB_DP", "bidirectional", "right"),
    # 顶部电源
    ("1", "IOVDD", "power_in", "top"),
    ("10", "IOVDD", "power_in", "top"),
    ("22", "IOVDD", "power_in", "top"),
    ("33", "IOVDD", "power_in", "top"),
    ("42", "IOVDD", "power_in", "top"),
    ("49", "IOVDD", "power_in", "top"),
    ("23", "DVDD", "power_in", "top"),
    ("50", "DVDD", "power_in", "top"),
    ("44", "VREG_VIN", "power_in", "top"),
    ("48", "USB_VDD", "power_in", "top"),
    ("43", "ADC_AVDD", "power_in", "top"),
    # 底部特殊引脚
    ("57", "GND", "power_in", "bottom"),
    ("45", "VREG_VOUT", "power_out", "bottom"),
    ("19", "TESTEN", "input", "bottom"),
    ("26", "RUN", "input", "bottom"),
    ("24", "SWCLK", "input", "bottom"),
    ("25", "SWD", "bidirectional", "bottom"),
    ("20", "XIN", "passive", "bottom"),
    ("21", "XOUT", "passive", "bottom"),
]

SPEC = {
    "name": "RP2040",
    "reference": "U",
    "description": "Raspberry Pi RP2040 Dual-core ARM Cortex-M0+ MCU, 133MHz, 264KB SRAM, QFN-56",
    "footprint": "Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm",
    "datasheet": "https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf",
    # 布局参数：左右 GPIO 间距 3.81mm（=3*1.27，在 1.27 网格上，防 ERC off_grid；
    #   GPIO 名 3.15mm 不重叠）；顶部/底部电源间距 5.08mm（=4*1.27，也在网格上）
    "layout": {"left_spacing": 3.81, "pin_spacing": 5.08},
    "pins": [{"number": n, "name": nm, "type": t, "side": s} for n, nm, t, s in PINS],
}


async def main() -> None:
    print(await asyncio.to_thread(
        kicad_sch_create_custom_symbol, json.dumps(SPEC, ensure_ascii=False),
        "", SCH, True))


if __name__ == "__main__":
    asyncio.run(main())
