#!/usr/bin/env python3
"""重绘 keyboard_main.kicad_sch: 全部用同名 net label 网络连接 (最可靠)。"""
import json
import sys
sys.path.insert(0, "src")

from kicad_mcp.client import KiCadClient
from kicad_mcp.tools.schematic import (
    _sch_context, _read_symbols, kicad_sch_add_symbol,
    kicad_sch_place_symbols_grid, kicad_sch_add_text, kicad_sch_add_line,
    kicad_sch_check_layout)
from kicad_mcp.proto.schematic import schematic_types_pb2 as st
from kicad_mcp.proto.common.types import enums_pb2 as en

MM = 10_000


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


def nc_i(x, y):
    n = st.NoConnect()
    n.position.x_nm = int(x); n.position.y_nm = int(y)
    return n


url, header = _sch_context()
with KiCadClient(url, client_name="main5") as kc:
    got = kc.get_items(header, [en.KOT_SCH_SYMBOL, en.KOT_SCH_TEXT, en.KOT_SCH_LINE,
                                en.KOT_SCH_LABEL, en.KOT_SCH_NO_CONNECT, en.KOT_SCH_SHAPE])
    ids = []
    for a in got.items:
        for cls in (st.Symbol, st.Text, st.Line, st.LocalLabel, st.NoConnect, st.Shape):
            if a.Is(cls.DESCRIPTOR):
                m = cls(); a.Unpack(m); ids.append(m.id.value); break
    if ids:
        r = kc.delete_items(header, ids)
        print(f"清空: {sum(1 for x in r.deleted_items if x.status == 1)}")

# 放符号
print(kicad_sch_add_symbol("keyboard-89_local", "RP2040", 150, 100, "U1", "RP2040"))
print(kicad_sch_add_symbol("power", "+3V3", 150, 52, "PWR3", "+3V3"))
print(kicad_sch_add_symbol("power", "GND", 90, 52, "PWRG", "GND"))
caps = [{"lib": "Device", "entry": "C", "ref": f"C{i}", "value": "100nF"}
        for i in range(1, 4)]
print(kicad_sch_place_symbols_grid(json.dumps(caps), columns=3, col_gap_mm=8.0,
                                   row_gap_mm=8.0, x0_mm=200, y0_mm=62))
print(kicad_sch_add_symbol("Device", "Crystal", 100, 180, "Y1", "12MHz"))
print(kicad_sch_add_symbol("Device", "C", 120, 180, "C5", "12pF"))
print(kicad_sch_add_symbol("Device", "C", 80, 180, "C6", "12pF"))
print(kicad_sch_add_symbol("Device", "R", 168, 180, "R1", "10k"))

syms = _read_symbols()
u1 = syms["U1"]["pins"]
y1 = syms["Y1"]["pins"]
r1 = syms["R1"]["pins"]
c1 = syms["C1"]["pins"]; c2 = syms["C2"]["pins"]; c3 = syms["C3"]["pins"]
c5 = syms["C5"]["pins"]; c6 = syms["C6"]["pins"]
pwr3 = syms["PWR3"]["pins"]; pwrg = syms["PWRG"]["pins"]

VDD_NUMS = ["1", "10", "22", "33", "42", "49", "23", "50", "43", "48", "44"]
GND_NUMS = ["57", "45", "19"]   # 57 GND, 45 VREG_VOUT, 19 TESTEN

wires, labels, ncs = [], [], []


def nwl(t, pos_list):
    """给一组引脚画 wire+同名 label"""
    for (ix, iy) in pos_list:
        wires.append(wire_i(ix, iy, ix, iy + 3 * MM))
        labels.append(label_i(t, ix, iy + 3 * MM))


def nwl2(t, pos_list):
    """向上画 wire+label (用于 +3V3 顶部)"""
    for (ix, iy) in pos_list:
        wires.append(wire_i(ix, iy, ix, iy - 3 * MM))
        labels.append(label_i(t, ix, iy - 3 * MM))


# +3V3 网络 (顶部 VDD + 电源符号 + 去耦 pin1 + R1 上端)
vdd_pos = [u1[n] for n in VDD_NUMS if n in u1]
nwl2("+3V3", vdd_pos)
p3 = list(pwr3.values())[0]
nwl2("+3V3", [p3])
c1p1 = c1["1"]; c2p1 = c2["1"]; c3p1 = c3["1"]
nwl2("+3V3", [c1p1, c2p1, c3p1])
r1p2 = r1["2"]
nwl2("+3V3", [r1p2])

# GND 网络
gnd_pos = [u1[n] for n in GND_NUMS if n in u1]
nwl("GND", gnd_pos)
pg = list(pwrg.values())[0]
nwl("GND", [pg])
c1p2 = c1["2"]; c2p2 = c2["2"]; c3p2 = c3["2"]
nwl("GND", [c1p2, c2p2, c3p2])
c5p2 = c5["2"]; c6p2 = c6["2"]
nwl("GND", [c5p2, c6p2])

# XIN 网络: XIN(20) + C5 pin1 + Y1.1
nwl("XIN", [u1["20"], c5["1"], y1["1"]])
# XOUT 网络: XOUT(21) + C6 pin1 + Y1.2
nwl("XOUT", [u1["21"], c6["1"], y1["2"]])

# RUN 网络: RUN(26) + R1 pin1
nwl("RUN", [u1["26"], r1["1"]])

# 调试/接口: wire+label
for n, lab in [("24", "SWCLK"), ("25", "SWD"), ("46", "USB_DM"), ("47", "USB_DP")]:
    if n in u1:
        ix, iy = u1[n]
        wires.append(wire_i(ix, iy, ix + 3 * MM, iy))
        labels.append(label_i(lab, ix + 3 * MM, iy))
# QSPI: 接 flash 页
for n, lab in [("56", "FLASH_CS"), ("52", "FLASH_SCLK"), ("53", "FLASH_SD0"),
               ("55", "FLASH_SD1"), ("54", "FLASH_SD2"), ("51", "FLASH_SD3")]:
    if n in u1:
        ix, iy = u1[n]
        wires.append(wire_i(ix, iy, ix + 3 * MM, iy))
        labels.append(label_i(lab, ix + 3 * MM, iy))

# GPIO 未用 -> no_connect (已连 VDD/GND/晶振/复位/调试/QSPI/USB 之外)
connected = set(VDD_NUMS + GND_NUMS + ["20", "21", "26", "24", "25",
                                       "46", "47", "51", "52", "53", "54", "55", "56"])
for n, (ix, iy) in u1.items():
    if n not in connected:
        ncs.append(nc_i(ix, iy))

with KiCadClient(url, client_name="main5") as kc:
    r = kc.create_items(header, wires + labels + ncs)
    print(f"网络+no_connect: {len(wires)+len(labels)+len(ncs)} ok={sum(1 for c in r.created_items if c.status.code==1)}")

# 框 + 标题
print(kicad_sch_add_line(45, 50, 280, 50, "notes"))
print(kicad_sch_add_line(45, 205, 280, 205, "notes"))
print(kicad_sch_add_line(45, 50, 45, 205, "notes"))
print(kicad_sch_add_line(280, 50, 280, 205, "notes"))
print(kicad_sch_add_text("KEYBOARD 89 - 主控 MCU (RP2040)", 162, 38, 4.5))
print(kicad_sch_add_text("电源/时钟/复位/调试 · 未用 GPIO 打 X", 162, 52, 2.0))
print(kicad_sch_add_text("USB/QSPI 网络 → 见 power/flash 页", 230, 62, 1.8))
print(kicad_sch_add_text("矩阵 GPIO → 见 matrix 页", 162, 213, 2.0))

print(kicad_sch_check_layout())
print("完成")
