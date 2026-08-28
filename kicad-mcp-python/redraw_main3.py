#!/usr/bin/env python3
"""用新 MCP 工具重绘 keyboard_main.kicad_sch (RP2040 最小系统)。

使用新工具: get_sheet_info / add_symbol(avoid_overlap) / place_symbols_grid /
connect(auto_avoid) / add_no_connect / check_layout
"""
import json
import sys
sys.path.insert(0, "src")

from kicad_mcp.client import KiCadClient
from kicad_mcp.tools.schematic import (
    _sch_context, _read_symbols, kicad_sch_add_symbol,
    kicad_sch_place_symbols_grid, kicad_sch_connect,
    kicad_sch_add_no_connect, kicad_sch_add_text,
    kicad_sch_check_layout, kicad_sch_get_sheet_info,
    kicad_sch_add_line, kicad_sch_add_label)
from kicad_mcp.proto.schematic import schematic_types_pb2 as st
from kicad_mcp.proto.common.types import enums_pb2 as en

MM = 10_000

print("=== 1. 页面信息 ===")
print(kicad_sch_get_sheet_info())

url, header = _sch_context()
with KiCadClient(url, client_name="main3") as kc:
    # 清空全部 (含 global label)
    got = kc.get_items(header, [en.KOT_SCH_SYMBOL, en.KOT_SCH_TEXT, en.KOT_SCH_LINE,
                                en.KOT_SCH_LABEL, en.KOT_SCH_GLOBAL_LABEL,
                                en.KOT_SCH_NO_CONNECT, en.KOT_SCH_SHAPE])
    ids = []
    for a in got.items:
        for cls in (st.Symbol, st.Text, st.Line, st.LocalLabel, st.GlobalLabel,
                    st.NoConnect, st.Shape):
            if a.Is(cls.DESCRIPTOR):
                m = cls(); a.Unpack(m); ids.append(m.id.value); break
    if ids:
        r = kc.delete_items(header, ids)
        print(f"清空: {sum(1 for x in r.deleted_items if x.status == 1)}/{len(ids)}")

print("\n=== 2. 放置 RP2040 ===")
print(kicad_sch_add_symbol("keyboard-89_local", "RP2040", 150, 95, "U1", "RP2040"))

# 读 RP2040 引脚
syms = _read_symbols()
u1 = syms["U1"]["pins"]   # {num: (ix, iy)}
print(f"RP2040 引脚数: {len(u1)}")

# 分类引脚
VDD_NAMES = ("IOVDD", "DVDD", "ADC_AVDD", "USB_VDD", "VREG_VIN")
# 需要引脚名 -> 从 symbol 信息... _read_symbols 只存 number. 用已知 number.
# 用 number 查询引脚名 (通过 get_symbol_pins 已有, 这里硬编码关键引脚号)
XIN, XOUT = "20", "21"
RUN = "26"
VREG_VOUT, TESTEN = "45", "19"
GND_NUMS = ["57"]
# VDD 电源脚 (顶部): 1,10,22,33,42,49 IOVDD; 23,50 DVDD; 43 ADC_AVDD; 48 USB_VDD; 44 VREG_VIN
VDD_NUMS = ["1", "10", "22", "33", "42", "49", "23", "50", "43", "48", "44"]

print("\n=== 3. 电源符号 + 去耦电容 ===")
print(kicad_sch_add_symbol("power", "+3V3", 150, 55, "PWR3", "+3V3"))
print(kicad_sch_add_symbol("power", "GND", 90, 55, "PWRG", "GND"))
# 去耦电容 (顶部右侧, 网格排布)
caps = [{"lib": "Device", "entry": "C", "ref": f"C{i}", "value": "100nF"}
        for i in range(1, 4)]
print(kicad_sch_place_symbols_grid(json.dumps(caps), columns=3, col_gap_mm=8.0,
                                   row_gap_mm=8.0, x0_mm=198, y0_mm=62))

print("\n=== 4. 晶振 + 复位 ===")
print(kicad_sch_add_symbol("Device", "Crystal", 100, 178, "Y1", "12MHz"))
print(kicad_sch_add_symbol("Device", "C", 118, 178, "C5", "12pF"))
print(kicad_sch_add_symbol("Device", "C", 82, 178, "C6", "12pF"))
print(kicad_sch_add_symbol("Device", "R", 165, 178, "R1", "10k"))

# 重新读所有符号 (含新放的)
syms = _read_symbols()
u1 = syms["U1"]["pins"]

print("\n=== 5. 电源连接 (VDD 脚 -> +3V3 label) ===")
wires = []
labels = []
def wire_i(x1, y1, x2, y2):
    ln = st.Line()
    ln.start.x_nm = int(x1); ln.start.y_nm = int(y1)
    ln.end.x_nm = int(x2); ln.end.y_nm = int(y2)
    ln.layer = st.SL_WIRE
    return ln
def label_i(t, x, y):
    lab = st.LocalLabel()
    lab.text.text.text = t
    lab.position.x_nm = int(x); lab.position.y_nm = int(y)
    return lab

for n in VDD_NUMS:
    if n in u1:
        ix, iy = u1[n]
        wires.append(wire_i(ix, iy, ix, iy - 3 * MM))
        labels.append(label_i("+3V3", ix, iy - 3 * MM))
# GND 脚
for n in GND_NUMS + [VREG_VOUT, TESTEN]:
    if n in u1:
        ix, iy = u1[n]
        wires.append(wire_i(ix, iy, ix, iy + 3 * MM))
        labels.append(label_i("GND", ix, iy + 3 * MM))
with KiCadClient(url, client_name="main3") as kc:
    r = kc.create_items(header, wires + labels)
    print(f"电源网络: {len(wires) + len(labels)} ok={sum(1 for c in r.created_items if c.status.code==1)}")

print("\n=== 6. 晶振/复位连接 (connect auto_avoid) ===")
try:
    print(kicad_sch_connect("U1", XIN, "Y1", "1"))
    print(kicad_sch_connect("U1", XOUT, "Y1", "2"))
    print(kicad_sch_connect("U1", RUN, "R1", "1"))
except Exception as e:
    print("connect 部分失败:", str(e)[:100])

print("\n=== 7. no_connect 未用 GPIO ===")
# 未用 = 除 VDD/GND/晶振/复位/USB/QSPI/SWD 外的全部
used = set(VDD_NUMS + GND_NUMS + [XIN, XOUT, RUN, VREG_VOUT, TESTEN,
                                 "24", "25",  # SWCLK, SWD
                                 "46", "47",  # USB_DM/DP
                                 "51", "52", "53", "54", "55", "56"])  # QSPI
ncs = []
for n, (ix, iy) in u1.items():
    if n in used:
        continue
    nc = st.NoConnect()
    nc.position.x_nm = int(ix); nc.position.y_nm = int(iy)
    ncs.append(nc)
with KiCadClient(url, client_name="main3") as kc:
    r = kc.create_items(header, ncs)
    print(f"no_connect: {len(ncs)} ok={sum(1 for c in r.created_items if c.status.code==1)}")

print("\n=== 8. 框 + 标题 + 说明 ===")
print(kicad_sch_add_line(45, 50, 275, 50, "notes"))
print(kicad_sch_add_line(45, 205, 275, 205, "notes"))
print(kicad_sch_add_line(45, 50, 45, 205, "notes"))
print(kicad_sch_add_line(275, 50, 275, 205, "notes"))
print(kicad_sch_add_text("KEYBOARD 89 - 主控 MCU (RP2040)", 160, 38, 4.5))
print(kicad_sch_add_text("时钟/电源/复位/调试 · 未用 GPIO 打 X 不连接", 160, 52, 2.2))
print(kicad_sch_add_text("USB/QSPI → 见 power/flash 页", 230, 62, 1.8))
print(kicad_sch_add_text("矩阵 GPIO → 见 matrix 页", 160, 213, 2.0))

print("\n=== 9. check_layout 验证 ===")
print(kicad_sch_check_layout())

print("\n完成")
