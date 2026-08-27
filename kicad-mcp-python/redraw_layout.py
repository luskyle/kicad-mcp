#!/usr/bin/env python3
"""重绘 keyboard_layout.kicad_sch 为专业分区总览图。

流程:
1. 清空全部现有元素
2. 画 4 个分区矩形框 (Shape)
3. 按分区放置各符号 (add_symbol)
4. 关键引脚画短 wire + 放置 net label
5. 加标题/说明文字
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


# 符号库 id
RP2040 = ("keyboard-89_local", "RP2040")
YXC = ("keyboard-89_local", "YXC")
LDO = ("keyboard-89_local", "LDO")
C100 = ("keyboard-89_local", "C-100nF")
GD25 = ("keyboard-89_local", "GD25Q16E")
PIN5P = ("keyboard-89_local", "PIN-5P")
USBC = ("keyboard-89_local", "USBC")
SW = ("keyboard-89_local", "TC-6601-5-160G")
PWR = ("power", "PWR_FLAG")


def make_symbol(lib, name, ref, x_mm, y_mm, orient=0, value=None):
    s = st.Symbol()
    s.lib_id.library_nickname = lib
    s.lib_id.entry_name = name
    s.position.x_nm = rnd(x_mm)
    s.position.y_nm = rnd(y_mm)
    s.orientation_degrees = orient
    f1 = s.fields.add(); f1.name = "Reference"; f1.value = ref
    f2 = s.fields.add(); f2.name = "Value"; f2.value = value or name
    return s


def make_shape(rect, label=None, w_mm=0.25):
    """rect=(x1,y1,x2,y2) 绝对坐标, notes 层矩形框"""
    sh = st.Shape()
    sh.stroke_width = round(w_mm * MM)
    sh.layer = st.SL_NOTES
    r = sh.graphic.rectangle
    r.top_left.x_nm = rnd(rect[0]); r.top_left.y_nm = rnd(rect[1])
    r.bottom_right.x_nm = rnd(rect[2]); r.bottom_right.y_nm = rnd(rect[3])
    sh.graphic.attributes.stroke.width.value_nm = round(w_mm * MM)
    sh.graphic.attributes.stroke.style = en.SLS_SOLID
    sh.graphic.attributes.fill.fill_type = bt.GFT_UNFILLED
    return sh


def make_line(x1, y1, x2, y2, layer="notes"):
    ln = st.Line()
    ln.start.x_nm = rnd(x1); ln.start.y_nm = rnd(y1)
    ln.end.x_nm = rnd(x2); ln.end.y_nm = rnd(y2)
    ln.layer = {"notes": st.SL_NOTES, "wire": st.SL_WIRE}[layer]
    return ln


def make_label(text, x_mm, y_mm):
    """本地网络标签 (net label)"""
    lab = st.LocalLabel()
    lab.text.text.text = text
    lab.position.x_nm = rnd(x_mm)
    lab.position.y_nm = rnd(y_mm)
    return lab


def make_text(text, x_mm, y_mm, height_mm=3.0, orient=0):
    t = st.Text()
    t.text.position.x_nm = rnd(x_mm)
    t.text.position.y_nm = rnd(y_mm)
    t.text.attributes.size.x_nm = rnd(height_mm)
    t.text.attributes.size.y_nm = rnd(height_mm)
    t.text.text = text
    return t


url, header = _sch_context()
print("connected:", url)

with KiCadClient(url, client_name="redraw") as kc:
    # ============ 1. 清空 ============
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
    else:
        print("清空: 无元素")

    # ============ 2. 分区框 ============
    boxes = [
        make_shape((40, 75, 175, 180), "A"),            # USB+电源
        make_shape((195, 75, 350, 190), "B"),            # MCU
        make_shape((370, 75, 455, 175), "C"),            # Flash
        make_shape((40, 200, 300, 285), "D"),            # 矩阵
        make_shape((320, 200, 455, 285), "E"),           # 矩阵说明
    ]
    resp = kc.create_items(header, boxes)
    print(f"分区框: {len(boxes)} 个, ok={sum(1 for c in resp.created_items if c.status.code==1)}")

    # ============ 3. 放置符号 ============
    syms = [
        # A 区: USB + 电源
        make_symbol(*USBC, "J1", 95, 118, 0, "USB-C"),
        make_symbol(*LDO, "U2", 150, 150, 0, "LDO 3V3"),
        make_symbol(*C100, "C1", 152, 100, 0, "100nF"),
        make_symbol(*PWR, "PWR0", 60, 95, 0, "+3V3"),
        # B 区: MCU
        make_symbol(*RP2040, "U1", 272, 132, 0, "RP2040"),
        make_symbol(*YXC, "Y1", 315, 95, 0, "12MHz"),
        # C 区: Flash
        make_symbol(*GD25, "U3", 412, 125, 0, "GD25Q16E"),
        # D 区: 矩阵接口 + 键示意
        make_symbol(*PIN5P, "J2", 70, 250, 0, "矩阵接口"),
    ]
    # 15 键网格 (5列 x 3行)
    kx0, ky0, kdx, kdy = 140.0, 215.0, 15.24, 12.7
    for i in range(15):
        col, row = i % 5, i // 5
        syms.append(make_symbol(*SW, f"K{i+1}", kx0 + col*kdx, ky0 + row*kdy, 0, "SW"))
    resp = kc.create_items(header, syms)
    ok = sum(1 for c in resp.created_items if c.status.code == 1)
    print(f"符号: {len(syms)} 个, ok={ok}")

    # ============ 4. 关键 net label (需在 wire 上) ============
    # 简单起见: 在分区边缘画短 wire + label
    labels_wires = []
    # A 区: VBUS / +3V3 / GND
    for (tx, ty, label) in [(60, 85, "+3V3"), (60, 165, "GND"), (125, 165, "VBUS")]:
        labels_wires.append(make_line(tx, ty, tx + 5, ty, "wire"))
        labels_wires.append(make_label(label, tx + 5, ty))
    # B 区: 复位 / SWD
    for (tx, ty, label) in [(220, 165, "SWCLK"), (235, 165, "SWD")]:
        labels_wires.append(make_line(tx, ty, tx + 5, ty, "wire"))
        labels_wires.append(make_label(label, tx + 5, ty))
    # C 区: FLASH 信号
    for (tx, ty, label) in [(395, 165, "FLASH_CS"), (405, 165, "FLASH_SCLK"),
                            (415, 165, "FLASH_SD0"), (425, 165, "FLASH_SD1")]:
        labels_wires.append(make_line(tx, ty, tx + 5, ty, "wire"))
        labels_wires.append(make_label(label, tx + 5, ty))
    # D 区: 行列信号
    for (tx, ty, label) in [(130, 205, "R1"), (145, 205, "R2"), (160, 205, "R3")]:
        labels_wires.append(make_line(tx, ty, tx + 5, ty, "wire"))
        labels_wires.append(make_label(label, tx + 5, ty))
    resp = kc.create_items(header, labels_wires)
    print(f"标签+短线: {len(labels_wires)} 个, ok={sum(1 for c in resp.created_items if c.status.code==1)}")

    # ============ 5. 标题/说明文字 ============
    texts = [
        make_text("KEYBOARD 89 - 系统原理图总览", 240, 45, 5.0),
        make_text("4 页架构: USB/电源 / 主控 MCU / Flash / 键盘矩阵", 240, 58, 2.5),
        make_text("A: USB 接口与电源", 70, 72, 2.5),
        make_text("B: 主控 MCU (RP2040)", 210, 72, 2.5),
        make_text("C: Flash 存储", 385, 72, 2.5),
        make_text("D: 键盘矩阵 (示意 5x3, 完整 5x22 见 matrix 页)", 55, 197, 2.5),
        make_text("E: 说明", 335, 197, 2.5),
        make_text("每键串联 1N4148W 二极管 (阳极接行, 阴极接列) 防串扰", 330, 220, 2.0),
        make_text("行列信号: R1-R3 (行), C1-C5 (列) 接 RP2040 GPIO", 330, 235, 2.0),
        make_text("未用 GPIO 引脚放置 X 不连接标记", 330, 250, 2.0),
    ]
    resp = kc.create_items(header, texts)
    print(f"文字: {len(texts)} 个, ok={sum(1 for c in resp.created_items if c.status.code==1)}")

print("完成")
