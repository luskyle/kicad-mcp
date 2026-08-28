#!/usr/bin/env python3
"""用新 MCP 工具绘制 keyboard_flash.kicad_sch (GD25Q16E SPI Flash)。"""
import sys
sys.path.insert(0, "src")

from kicad_mcp.client import KiCadClient
from kicad_mcp.tools.schematic import (
    _sch_context, _read_symbols, kicad_sch_add_symbol, kicad_sch_add_text,
    kicad_sch_add_line, kicad_sch_check_layout)
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
with KiCadClient(url, client_name="flash") as kc:
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
print(kicad_sch_add_symbol("Memory_Flash", "GD25QxxxEY", 150, 110, "U3", "GD25Q16E"))
print(kicad_sch_add_symbol("Device", "C", 200, 100, "C1", "100nF"))
print(kicad_sch_add_symbol("power", "+3V3", 150, 55, "PWR3", "+3V3"))
print(kicad_sch_add_symbol("power", "GND", 100, 165, "PWRG", "GND"))

syms = _read_symbols()
u3 = syms["U3"]["pins"]
c1 = syms["C1"]["pins"]
pwr3 = syms["PWR3"]["pins"]; pwrg = syms["PWRG"]["pins"]

# GD25QxxxEY: 1=CS 2=SO 3=WP 4=VSS 5=SI 6=SCLK 7=HOLD 8=VCC 9=PAD
wires, labels, ncs = [], [], []
cx = round(syms["U3"]["x_mm"] * MM)
cy = round(syms["U3"]["y_mm"] * MM)


def dir_lab(t, n):
    """按引脚方向画 wire+label (左右引脚水平, 上下引脚垂直)"""
    ix, iy = u3[n]
    if abs(ix - cx) >= abs(iy - cy):       # 水平引脚 (左右)
        if ix < cx:
            wires.append(wire_i(ix, iy, ix - 3 * MM, iy))
            labels.append(label_i(t, ix - 3 * MM, iy))
        else:
            wires.append(wire_i(ix, iy, ix + 3 * MM, iy))
            labels.append(label_i(t, ix + 3 * MM, iy))
    else:                                   # 垂直引脚 (上下)
        if iy < cy:
            wires.append(wire_i(ix, iy, ix, iy - 3 * MM))
            labels.append(label_i(t, ix, iy - 3 * MM))
        else:
            wires.append(wire_i(ix, iy, ix, iy + 3 * MM))
            labels.append(label_i(t, ix, iy + 3 * MM))


flash_map = {"1": "FLASH_CS", "6": "FLASH_SCLK", "5": "FLASH_SD0", "2": "FLASH_SD1"}
for n, lab in flash_map.items():
    if n in u3:
        dir_lab(lab, n)
if "8" in u3:        # VCC
    dir_lab("+3V3", "8")
if "4" in u3:        # VSS
    dir_lab("GND", "4")
if "9" in u3:        # PAD
    dir_lab("GND", "9")
if "3" in u3:        # WP 上拉
    dir_lab("+3V3", "3")
if "7" in u3:        # HOLD 上拉
    dir_lab("+3V3", "7")

# 去耦 C1: +3V3/GND
c_items = list(c1.values())
if len(c_items) >= 2:
    p1, p2 = c_items[0], c_items[1]
    wires.append(wire_i(p1[0], p1[1], p1[0], p1[1] - 3 * MM))
    labels.append(label_i("+3V3", p1[0], p1[1] - 3 * MM))
    wires.append(wire_i(p2[0], p2[1], p2[0], p2[1] + 3 * MM))
    labels.append(label_i("GND", p2[0], p2[1] + 3 * MM))

# 电源符号连接 (必须, 否则孤立网络)
p3 = list(pwr3.values())[0]
wires.append(wire_i(p3[0], p3[1], p3[0], p3[1] - 3 * MM))
labels.append(label_i("+3V3", p3[0], p3[1] - 3 * MM))
pg = list(pwrg.values())[0]
wires.append(wire_i(pg[0], pg[1], pg[0], pg[1] + 3 * MM))
labels.append(label_i("GND", pg[0], pg[1] + 3 * MM))

with KiCadClient(url, client_name="flash") as kc:
    r = kc.create_items(header, wires + labels + ncs)
    print(f"网络: {len(wires) + len(labels) + len(ncs)} ok={sum(1 for c in r.created_items if c.status.code==1)}")

print("=== 2. 框 + 标题 ===")
print(kicad_sch_add_line(40, 50, 250, 50, "notes"))
print(kicad_sch_add_line(40, 175, 250, 175, "notes"))
print(kicad_sch_add_line(40, 50, 40, 175, "notes"))
print(kicad_sch_add_line(250, 50, 250, 175, "notes"))
print(kicad_sch_add_text("KEYBOARD 89 - Flash 存储 (GD25Q16E)", 145, 38, 4.0))
print(kicad_sch_add_text("SPI: CS/SCLK/SD0/SD1 → RP2040 QSPI", 145, 183, 2.0))

print("=== 3. check_layout ===")
print(kicad_sch_check_layout())
print("完成")
