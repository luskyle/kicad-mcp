#!/usr/bin/env python3
"""生成 keyboard-89 自定义符号库 (RP2040 等) 到 keyboard-89_local.kicad_symdir。"""
import json
import sys
sys.path.insert(0, "src")

from kicad_mcp.symbol_writer import parse_spec, write_symdir

# RP2040 QFN-56 引脚 (number, name, type, side)
RP2040_PINS = [
    # 顶部电源
    ("1", "IOVDD", "power_in", "top"), ("10", "IOVDD", "power_in", "top"),
    ("22", "IOVDD", "power_in", "top"), ("33", "IOVDD", "power_in", "top"),
    ("42", "IOVDD", "power_in", "top"), ("49", "IOVDD", "power_in", "top"),
    ("23", "DVDD", "power_in", "top"), ("50", "DVDD", "power_in", "top"),
    ("43", "ADC_AVDD", "power_in", "top"), ("48", "USB_VDD", "power_in", "top"),
    ("44", "VREG_VIN", "power_in", "top"),
    # 底部
    ("20", "XIN", "passive", "bottom"), ("21", "XOUT", "passive", "bottom"),
    ("24", "SWCLK", "input", "bottom"), ("25", "SWD", "bidirectional", "bottom"),
    ("26", "RUN", "input", "bottom"), ("19", "TESTEN", "input", "bottom"),
    ("45", "VREG_VOUT", "power_out", "bottom"), ("57", "GND", "power_in", "bottom"),
    # 左侧 GPIO0-15
    ("2", "GPIO0", "bidirectional", "left"), ("3", "GPIO1", "bidirectional", "left"),
    ("4", "GPIO2", "bidirectional", "left"), ("5", "GPIO3", "bidirectional", "left"),
    ("6", "GPIO4", "bidirectional", "left"), ("7", "GPIO5", "bidirectional", "left"),
    ("8", "GPIO6", "bidirectional", "left"), ("9", "GPIO7", "bidirectional", "left"),
    ("11", "GPIO8", "bidirectional", "left"), ("12", "GPIO9", "bidirectional", "left"),
    ("13", "GPIO10", "bidirectional", "left"), ("14", "GPIO11", "bidirectional", "left"),
    ("15", "GPIO12", "bidirectional", "left"), ("16", "GPIO13", "bidirectional", "left"),
    ("17", "GPIO14", "bidirectional", "left"), ("18", "GPIO15", "bidirectional", "left"),
    # 右侧 GPIO16-29 + USB + QSPI
    ("27", "GPIO16", "bidirectional", "right"), ("28", "GPIO17", "bidirectional", "right"),
    ("29", "GPIO18", "bidirectional", "right"), ("30", "GPIO19", "bidirectional", "right"),
    ("31", "GPIO20", "bidirectional", "right"), ("32", "GPIO21", "bidirectional", "right"),
    ("34", "GPIO22", "bidirectional", "right"), ("35", "GPIO23", "bidirectional", "right"),
    ("36", "GPIO24", "bidirectional", "right"), ("37", "GPIO25", "bidirectional", "right"),
    ("38", "GPIO26", "bidirectional", "right"), ("39", "GPIO27", "bidirectional", "right"),
    ("40", "GPIO28", "bidirectional", "right"), ("41", "GPIO29", "bidirectional", "right"),
    ("46", "USB_DM", "bidirectional", "right"), ("47", "USB_DP", "bidirectional", "right"),
    ("51", "QSPI_SD3", "bidirectional", "right"), ("52", "QSPI_SCLK", "bidirectional", "right"),
    ("53", "QSPI_SD0", "bidirectional", "right"), ("54", "QSPI_SD2", "bidirectional", "right"),
    ("55", "QSPI_SD1", "bidirectional", "right"), ("56", "QSPI_CSn", "input", "right"),
]

RP2040_SPEC = {
    "name": "RP2040", "reference": "U",
    "description": "Raspberry Pi RP2040 Dual-Core Cortex-M0+ MCU",
    "footprint": "Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm",
    "layout": {"left_spacing": 2.54, "pin_spacing": 5.08},
    "pins": [{"number": n, "name": nm, "type": t, "side": sd}
             for n, nm, t, sd in RP2040_PINS],
}

# 5 引脚轻触开关 (TC-6601 简化为 4 脚: 1/2 一组, 3/4 一组)
SW_SPEC = {
    "name": "SW-TACT-5", "reference": "SW",
    "description": "Tactile push switch 5x5mm",
    "layout": {"left_spacing": 2.54, "pin_spacing": 2.54},
    "pins": [
        {"number": "1", "name": "1", "type": "passive", "side": "left"},
        {"number": "2", "name": "2", "type": "passive", "side": "left"},
        {"number": "3", "name": "3", "type": "passive", "side": "right"},
        {"number": "4", "name": "4", "type": "passive", "side": "right"},
    ],
}


def main():
    out_dir = "/home/luskyle/桌面/keyboard-89/keyboard-89_local.kicad_symdir"
    symbols = [parse_spec(json.dumps(RP2040_SPEC)),
               parse_spec(json.dumps(SW_SPEC))]
    write_symdir(symbols, out_dir)
    for s in symbols:
        print(f"  {s['name']}: {len(s['pins'])} pins")


if __name__ == "__main__":
    main()
