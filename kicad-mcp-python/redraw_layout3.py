#!/usr/bin/env python3
"""用新 MCP 工具绘制 keyboard_layout.kicad_sch (系统总览框图, A4)。"""
import sys
sys.path.insert(0, "src")

from kicad_mcp.client import KiCadClient
from kicad_mcp.tools.schematic import (
    _sch_context, kicad_sch_add_shape, kicad_sch_add_text,
    kicad_sch_add_line, kicad_sch_check_layout, kicad_sch_get_sheet_info)
from kicad_mcp.proto.schematic import schematic_types_pb2 as st
from kicad_mcp.proto.common.types import enums_pb2 as en

print("=== 页面 ===")
print(kicad_sch_get_sheet_info())

url, header = _sch_context()
with KiCadClient(url, client_name="layout3") as kc:
    got = kc.get_items(header, [en.KOT_SCH_SYMBOL, en.KOT_SCH_TEXT, en.KOT_SCH_LINE,
                                en.KOT_SCH_LABEL, en.KOT_SCH_SHAPE])
    ids = []
    for a in got.items:
        for cls in (st.Symbol, st.Text, st.Line, st.LocalLabel, st.Shape):
            if a.Is(cls.DESCRIPTOR):
                m = cls(); a.Unpack(m); ids.append(m.id.value); break
    if ids:
        r = kc.delete_items(header, ids)
        print(f"清空: {sum(1 for x in r.deleted_items if x.status == 1)}")

print("=== 1. 标题 ===")
print(kicad_sch_add_text("KEYBOARD 89 — 系统原理图总览", 210, 38, 6.0))
print(kicad_sch_add_text("4 页架构: 主控 / 电源 / Flash / 键盘矩阵", 210, 56, 2.6))

print("=== 2. 功能块 (矩形框) ===")
# A USB+电源
print(kicad_sch_add_shape("rectangle", "40,75;190,195", filled=False, stroke_width_mm=0.4))
print(kicad_sch_add_text("USB 接口与电源", 115, 100, 3.0))
print(kicad_sch_add_text("USB-C 座 (J1)", 115, 120, 2.2))
print(kicad_sch_add_text("AMS1117-3.3 LDO (U1)", 115, 138, 2.2))
print(kicad_sch_add_text("VBUS→3V3 · USB_DP/DM", 115, 156, 2.0))
# B 主控 MCU
print(kicad_sch_add_shape("rectangle", "210,75;390,195", filled=False, stroke_width_mm=0.4))
print(kicad_sch_add_text("主控 MCU (RP2040)", 300, 100, 3.0))
print(kicad_sch_add_text("U1 RP2040 · QFN-56", 300, 120, 2.2))
print(kicad_sch_add_text("12MHz 晶振 · 复位 · 去耦", 300, 138, 2.0))
print(kicad_sch_add_text("GPIO0-29 · USB · QSPI · ADC", 300, 156, 2.0))
# C Flash
print(kicad_sch_add_shape("rectangle", "40,210;180,265", filled=False, stroke_width_mm=0.4))
print(kicad_sch_add_text("Flash 存储", 110, 222, 2.4))
print(kicad_sch_add_text("GD25Q16E (U3) SPI", 110, 240, 2.0))
print(kicad_sch_add_text("QSPI: CS/SCLK/SD0/SD1", 110, 256, 1.8))
# D 矩阵
print(kicad_sch_add_shape("rectangle", "200,210;390,265", filled=False, stroke_width_mm=0.4))
print(kicad_sch_add_text("键盘矩阵", 295, 222, 2.4))
print(kicad_sch_add_text("5x22 扫描 · 89 键", 295, 240, 2.0))
print(kicad_sch_add_text("每键串 1N4148W 二极管", 295, 256, 1.8))

print("=== 3. 块间连线 (notes) ===")
print(kicad_sch_add_line(190, 160, 210, 160, "notes"))          # A->B
print(kicad_sch_add_line(300, 195, 300, 210, "notes"))          # B->D
print(kicad_sch_add_line(110, 195, 110, 210, "notes"))          # A->C

print("=== 4. 信号标注 + 说明 ===")
print(kicad_sch_add_text("3V3 / GND / USB_DP / USB_DM", 200, 170, 1.8))
print(kicad_sch_add_text("FLASH_CS/SCLK/SD0/SD1", 130, 208, 1.7))
print(kicad_sch_add_text("R1-R5 / C1-C22 → GPIO", 270, 208, 1.7))
print(kicad_sch_add_text("设计要点:", 40, 280, 2.0))
print(kicad_sch_add_text("1. USB-C 直连 RP2040 (无 HUB)   2. LDO 输出 3V3   3. QSPI 接 Flash", 40, 294, 1.8))
print(kicad_sch_add_text("4. 矩阵 5x22 扫描, 每键串 1N4148W 防串扰   5. 未用引脚 X 不连接", 40, 306, 1.8))

print("=== 5. check_layout ===")
print(kicad_sch_check_layout())
print("完成")
