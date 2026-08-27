#!/usr/bin/env python3
"""重绘 keyboard_layout.kicad_sch 为纯框图式系统总览 (notes 层, ERC 干净)。

采用分区功能块 + 文字标注 + notes 连线, 不放电气符号 → 无 ERC 错误。
各功能页 (main/power/flash/matrix) 负责真实电路连接。
"""
import sys
sys.path.insert(0, "src")

from kicad_mcp.client import KiCadClient
from kicad_mcp.tools.schematic import _sch_context
from kicad_mcp.proto.schematic import schematic_types_pb2 as st
from kicad_mcp.proto.common.types import base_types_pb2 as bt, enums_pb2 as en

MM = 10_000


def rnd(v):
    return round(v * MM)


def make_shape(rect, filled=False, w_mm=0.3):
    sh = st.Shape()
    sh.stroke_width = round(w_mm * MM)
    sh.layer = st.SL_NOTES
    r = sh.graphic.rectangle
    r.top_left.x_nm = rnd(rect[0]); r.top_left.y_nm = rnd(rect[1])
    r.bottom_right.x_nm = rnd(rect[2]); r.bottom_right.y_nm = rnd(rect[3])
    sh.graphic.attributes.stroke.width.value_nm = round(w_mm * MM)
    sh.graphic.attributes.stroke.style = en.SLS_SOLID
    sh.graphic.attributes.fill.fill_type = (bt.GFT_FILLED if filled
                                            else bt.GFT_UNFILLED)
    return sh


def make_line(x1, y1, x2, y2, w_mm=0.3):
    ln = st.Line()
    ln.start.x_nm = rnd(x1); ln.start.y_nm = rnd(y1)
    ln.end.x_nm = rnd(x2); ln.end.y_nm = rnd(y2)
    ln.layer = st.SL_NOTES
    return ln


def make_text(text, x_mm, y_mm, height_mm=2.5, center=True):
    t = st.Text()
    t.text.position.x_nm = rnd(x_mm)
    t.text.position.y_nm = rnd(y_mm)
    t.text.attributes.size.x_nm = rnd(height_mm)
    t.text.attributes.size.y_nm = rnd(height_mm)
    t.text.text = text
    return t


url, header = _sch_context()
print("connected:", url)

with KiCadClient(url, client_name="redraw2") as kc:
    # ===== 清空 =====
    got = kc.get_items(header, [en.KOT_SCH_SYMBOL, en.KOT_SCH_TEXT,
                                en.KOT_SCH_LINE, en.KOT_SCH_LABEL,
                                en.KOT_SCH_GLOBAL_LABEL, en.KOT_SCH_SHAPE])
    ids = []
    for a in got.items:
        for cls in (st.Symbol, st.Text, st.Line, st.LocalLabel,
                    st.GlobalLabel, st.Shape):
            if a.Is(cls.DESCRIPTOR):
                m = cls(); a.Unpack(m)
                ids.append(m.id.value)
                break
    if ids:
        resp = kc.delete_items(header, ids)
        print(f"清空: 删除 {sum(1 for r in resp.deleted_items if r.status==1)}/{len(ids)}")

    items = []

    # ===== 1. 5 个分区大框 =====
    items += [
        make_shape((40, 75, 175, 180), w_mm=0.4),    # A USB/电源
        make_shape((195, 75, 350, 190), w_mm=0.4),   # B MCU
        make_shape((370, 75, 455, 175), w_mm=0.4),   # C Flash
        make_shape((40, 200, 300, 285), w_mm=0.4),   # D 矩阵
        make_shape((320, 200, 455, 285), w_mm=0.4),  # E 说明
    ]

    # ===== 2. 功能块 (notes 矩形 + 块名 + 信号标注) =====
    # A: USB + 电源
    items += [
        make_shape((50, 85, 115, 165)),                     # USB-C 块
        make_text("USB-C 接口", 82, 122, 2.2),
        make_text("VBUS / D+ / D- / GND", 82, 132, 1.6),
        make_text("USB_DP / USB_DM → MCU", 82, 142, 1.6),
        make_shape((130, 85, 168, 165)),                    # LDO 块
        make_text("LDO 3V3", 149, 112, 2.0),
        make_text("VBUS→IN", 149, 125, 1.6),
        make_text("OUT→3V3", 149, 135, 1.6),
        make_text("C_out 100nF", 149, 148, 1.6),
    ]

    # B: MCU
    items += [
        make_shape((205, 88, 330, 175), w_mm=0.35),         # RP2040 块
        make_text("RP2040 主控 (U1)", 267, 108, 2.6),
        make_text("QFN-56 · GPIO0-29 · ADC · USB · PIO", 267, 120, 1.7),
        make_text("电源: 3V3 / GND · 去耦电容", 267, 132, 1.7),
        make_text("时钟: 12MHz 晶振 (Y1)", 267, 144, 1.7),
        make_text("复位: BOOT / RUN", 267, 156, 1.7),
        make_shape((303, 88, 345, 118), w_mm=0.25),         # 晶振块
        make_text("12MHz", 324, 103, 1.8),
    ]

    # C: Flash
    items += [
        make_shape((378, 88, 447, 165), w_mm=0.35),         # GD25Q16E 块
        make_text("Flash 存储 (U3)", 412, 110, 2.4),
        make_text("GD25Q16E 16Mbit", 412, 122, 1.7),
        make_text("CS / SCLK / SD0 / SD1", 412, 134, 1.7),
        make_text("→ RP2040 QSPI", 412, 146, 1.7),
    ]

    # D: 矩阵
    items += [
        make_shape((48, 212, 130, 275), w_mm=0.3),          # 矩阵接口块
        make_text("矩阵接口 (J2)", 89, 230, 2.0),
        make_text("行 R1-R5", 89, 243, 1.7),
        make_text("列 C1-C22", 89, 253, 1.7),
        make_shape((145, 212, 290, 275), w_mm=0.3),         # 键网络块
        make_text("键盘矩阵 5×22", 217, 228, 2.2),
        make_text("TC-6601 轻触开关 ×89", 217, 242, 1.7),
        make_text("每键串联 1N4148W", 217, 254, 1.7),
        make_text("(阳极接行, 阴极接列)", 217, 264, 1.6),
    ]

    # ===== 3. 块间示意连线 (notes) =====
    items += [
        # USB → MCU
        make_line(115, 145, 205, 145),
        make_line(168, 100, 205, 100),
        # 晶振 → MCU
        make_line(324, 118, 324, 160), make_line(324, 160, 330, 160),
        # MCU → Flash (QSPI)
        make_line(330, 120, 378, 120),
        # MCU → 矩阵
        make_line(267, 175, 267, 255), make_line(267, 255, 290, 255),
    ]

    # ===== 4. 标题与说明 =====
    items += [
        make_text("KEYBOARD 89 — 系统原理图总览", 240, 40, 5.0),
        make_text("4 页架构总览 · 详细电路见各功能页", 240, 55, 2.5),
        make_text("A: USB 接口与电源 (keyboard_power.sch)", 60, 73, 1.8),
        make_text("B: 主控 MCU (keyboard_main.sch)", 215, 73, 1.8),
        make_text("C: Flash 存储 (keyboard_flash.sch)", 380, 73, 1.8),
        make_text("D: 键盘矩阵 (keyboard_matrix.sch)", 55, 198, 1.8),
        make_text("E: 设计说明", 335, 198, 1.8),
        make_text("1. RP2040 QSPI 接 GD25Q16E (低电平使能 CS)", 333, 218, 1.7),
        make_text("2. USB-C 直连 RP2040 USB DP/DM (无 USB HUB)", 333, 232, 1.7),
        make_text("3. 电源由 VBUS 经 LDO 输出 3V3", 333, 246, 1.7),
        make_text("4. 矩阵行接 GPIO, 列接 ADC 复用 (需外扩或选通)", 333, 260, 1.7),
        make_text("5. 未用 GPIO 放置 X 不连接标记", 333, 274, 1.7),
    ]

    resp = kc.create_items(header, items)
    print(f"绘制: {len(items)} 个元素, ok={sum(1 for c in resp.created_items if c.status.code==1)}")

print("完成")
