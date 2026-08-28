#!/usr/bin/env python3
"""用新 MCP 工具绘制 keyboard_power.kicad_sch (USB-C + LDO 电源)。"""
import sys
sys.path.insert(0, "src")

from kicad_mcp.client import KiCadClient
from kicad_mcp.tools.schematic import (
    _sch_context, _read_symbols, kicad_sch_add_symbol, kicad_sch_add_text,
    kicad_sch_add_line, kicad_sch_check_layout, kicad_sch_get_sheet_info)
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
with KiCadClient(url, client_name="power") as kc:
    got = kc.get_items(header, [en.KOT_SCH_SYMBOL, en.KOT_SCH_TEXT, en.KOT_SCH_LINE,
                                en.KOT_SCH_LABEL, en.KOT_SCH_NO_CONNECT])
    ids = []
    for a in got.items:
        for cls in (st.Symbol, st.Text, st.Line, st.LocalLabel, st.NoConnect):
            if a.Is(cls.DESCRIPTOR):
                m = cls(); a.Unpack(m); ids.append(m.id.value); break
    if ids:
        r = kc.delete_items(header, ids)
        print(f"清空: {sum(1 for x in r.deleted_items if x.status == 1)}")

print("=== 1. 放置元件 ===")
print(kicad_sch_add_symbol("Connector", "USB_C_Receptacle", 60, 120, "J1", "USB-C"))
print(kicad_sch_add_symbol("Regulator_Linear", "AMS1117-3.3", 155, 120, "U1", "3.3V"))
print(kicad_sch_add_symbol("Device", "C", 130, 90, "C1", "10uF"))
print(kicad_sch_add_symbol("Device", "C", 180, 90, "C2", "10uF"))
print(kicad_sch_add_symbol("Device", "C", 180, 150, "C3", "100nF"))
print(kicad_sch_add_symbol("power", "+3V3", 220, 60, "PWR3", "+3V3"))
print(kicad_sch_add_symbol("power", "GND", 90, 175, "PWRG", "GND"))

# 读引脚
syms = _read_symbols()
j1 = syms["J1"]["pins"]
u1 = syms["U1"]["pins"]
c1, c2, c3 = syms["C1"]["pins"], syms["C2"]["pins"], syms["C3"]["pins"]
print(f"J1 pins={len(j1)} U1 pins={len(u1)}")

# 找 AMS1117 引脚 (IN/OUT/GND 或 number)
def find_pin(pins, names):
    for k, v in pins.items():
        # k 是 number, 但我们需要 name -> _read_symbols 只存 number
        pass
    return None

# AMS1117-3.3 引脚编号: 1=GND, 2=VOUT, 3=VIN (SOT-223) 或 1=VIN,2=GND,3=VOUT
# 读引脚位置后决定 (引脚 3 通常 VIN)
u1_items = sorted(u1.items())
print("U1 pins:", u1_items[:6])
j1_items = sorted(j1.items())

# 电源网络 (net label)
wires, labels, ncs = [], [], []

# AMS1117-3.3: 1=GND 2=VO(VOUT) 3=VI(VIN)
if "3" in u1:
    ix, iy = u1["3"]
    wires.append(wire_i(ix, iy, ix, iy - 3 * MM))
    labels.append(label_i("VBUS", ix, iy - 3 * MM))
if "2" in u1:
    ix, iy = u1["2"]
    wires.append(wire_i(ix, iy, ix, iy - 3 * MM))
    labels.append(label_i("+3V3", ix, iy - 3 * MM))
if "1" in u1:
    ix, iy = u1["1"]
    wires.append(wire_i(ix, iy, ix, iy + 3 * MM))
    labels.append(label_i("GND", ix, iy + 3 * MM))

# USB-C 关键脚: A4=VBUS A6=D+ A7=D- A1=GND (其余 no_connect)
usb_key = {"A4": "VBUS", "A6": "USB_DP", "A7": "USB_DM", "A1": "GND"}
for n, (ix, iy) in j1.items():
    if n in usb_key:
        lab = usb_key[n]
        wires.append(wire_i(ix, iy, ix - 3 * MM, iy))
        labels.append(label_i(lab, ix - 3 * MM, iy))
    else:
        ncs.append(nc_i(ix, iy))

# 去耦电容: C2(输出) 一端 +3V3 一端 GND
c2_items = list(c2.values())
if len(c2_items) >= 2:
    p1, p2 = c2_items[0], c2_items[1]
    wires.append(wire_i(p1[0], p1[1], p1[0], p1[1] - 3 * MM))
    labels.append(label_i("+3V3", p1[0], p1[1] - 3 * MM))
    wires.append(wire_i(p2[0], p2[1], p2[0], p2[1] + 3 * MM))
    labels.append(label_i("GND", p2[0], p2[1] + 3 * MM))
# C1 输入电容: VBUS/GND
c1_items = list(c1.values())
if len(c1_items) >= 2:
    p1, p2 = c1_items[0], c1_items[1]
    wires.append(wire_i(p1[0], p1[1], p1[0], p1[1] - 3 * MM))
    labels.append(label_i("VBUS", p1[0], p1[1] - 3 * MM))
    wires.append(wire_i(p2[0], p2[1], p2[0], p2[1] + 3 * MM))
    labels.append(label_i("GND", p2[0], p2[1] + 3 * MM))
# C3: +3V3/GND
c3_items = list(c3.values())
if len(c3_items) >= 2:
    p1, p2 = c3_items[0], c3_items[1]
    wires.append(wire_i(p1[0], p1[1], p1[0], p1[1] - 3 * MM))
    labels.append(label_i("+3V3", p1[0], p1[1] - 3 * MM))
    wires.append(wire_i(p2[0], p2[1], p2[0], p2[1] + 3 * MM))
    labels.append(label_i("GND", p2[0], p2[1] + 3 * MM))

with KiCadClient(url, client_name="power") as kc:
    r = kc.create_items(header, wires + labels + ncs)
    print(f"网络+no_connect: {len(wires)+len(labels)+len(ncs)} ok={sum(1 for c in r.created_items if c.status.code==1)}")

print("=== 2. 框 + 标题 ===")
print(kicad_sch_add_line(40, 50, 260, 50, "notes"))
print(kicad_sch_add_line(40, 190, 260, 190, "notes"))
print(kicad_sch_add_line(40, 50, 40, 190, "notes"))
print(kicad_sch_add_line(260, 50, 260, 190, "notes"))
print(kicad_sch_add_text("KEYBOARD 89 - 电源 (USB-C + LDO 3V3)", 150, 38, 4.0))
print(kicad_sch_add_text("VBUS 5V 经 AMS1117-3.3 输出 +3V3 · USB_DP/DM 直连 MCU", 150, 198, 2.0))

print("=== 3. check_layout ===")
print(kicad_sch_check_layout())
print("完成")
