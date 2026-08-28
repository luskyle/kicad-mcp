#!/usr/bin/env python3
"""用新 MCP 工具绘制 keyboard_layout.kicad_sch (系统总览框图, A3)。

布局规则: 全部元素 X 40-340, Y 28-260, 避开右下角标题栏(X>350/Y>268)
和页面边缘, 标题紧凑不占大量顶部空间。
"""
import sys
sys.path.insert(0, "src")

from kicad_mcp.client import KiCadClient
from kicad_mcp.tools.schematic import (
    _sch_context, kicad_sch_add_shape, kicad_sch_add_text,
    kicad_sch_add_line, kicad_sch_check_layout)
from kicad_mcp.proto.schematic import schematic_types_pb2 as st
from kicad_mcp.proto.common.types import enums_pb2 as en

url, header = _sch_context()
with KiCadClient(url, client_name="layout4") as kc:
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

# ===== 标题 (紧凑, 顶部) =====
print(kicad_sch_add_text("KEYBOARD 89 — 系统原理图总览", 210, 30, 4.0))
print(kicad_sch_add_text("4 页架构: 主控 / 电源 / Flash / 键位矩阵", 210, 42, 2.0))

# ===== 功能块 2x2 (避开右下标题栏) =====
# A 左上: USB + 电源
print(kicad_sch_add_shape("rectangle", "40,70;190,200", filled=False, stroke_width_mm=0.4))
print(kicad_sch_add_text("USB 供电电路", 115, 92, 2.6))
print(kicad_sch_add_text("USB-C 座 (J1)", 115, 112, 2.0))
print(kicad_sch_add_text("AMS1117-3.3 LDO (U1)", 115, 128, 2.0))
print(kicad_sch_add_text("VBUS→3V3 · USB_DP/DM", 115, 144, 1.8))
# B 右上: 主控
print(kicad_sch_add_shape("rectangle", "205,70;340,200", filled=False, stroke_width_mm=0.4))
print(kicad_sch_add_text("主控 MCU (RP2040)", 272, 92, 2.6))
print(kicad_sch_add_text("U1 RP2040 · QFN-56", 272, 112, 2.0))
print(kicad_sch_add_text("12MHz 晶振 · 复位", 272, 128, 2.0))
print(kicad_sch_add_text("GPIO · USB · QSPI · ADC", 272, 144, 1.8))
# C 左下: Flash
print(kicad_sch_add_shape("rectangle", "40,212;190,258", filled=False, stroke_width_mm=0.4))
print(kicad_sch_add_text("Flash 存储", 115, 224, 2.2))
print(kicad_sch_add_text("GD25Q16E (U3) SPI", 115, 240, 1.8))
# D 右下: 矩阵
print(kicad_sch_add_shape("rectangle", "205,212;340,258", filled=False, stroke_width_mm=0.4))
print(kicad_sch_add_text("键位矩阵", 272, 224, 2.2))
print(kicad_sch_add_text("5x22 扫描 · 89 键", 272, 240, 1.8))

# ===== 块间连线 (notes) =====
print(kicad_sch_add_line(190, 140, 205, 140, "notes"))   # A -> B
print(kicad_sch_add_line(115, 200, 115, 212, "notes"))   # A -> C
print(kicad_sch_add_line(272, 200, 272, 212, "notes"))   # B -> D
# 信号标注 (块间, 靠左避开标题栏)
print(kicad_sch_add_text("3V3 / USB_DP / USB_DM", 197, 132, 1.5))
print(kicad_sch_add_text("FLASH_CS/SCLK/SD0/SD1", 117, 206, 1.4))
print(kicad_sch_add_text("R1-R5 / C1-C22 → GPIO", 274, 206, 1.4))

# ===== 设计要点 (左下, 页面内, 避开标题栏) =====
print(kicad_sch_add_text("设计要点:  1.USB-C 直连 RP2040  2.LDO 输出 3V3  3.QSPI 接 Flash", 40, 264, 1.6))
print(kicad_sch_add_text("4.矩阵 5x22 扫描, 每键串 1N4148W  5.未用引脚 X 不连接", 40, 274, 1.6))

print(kicad_sch_check_layout())
print("完成")
