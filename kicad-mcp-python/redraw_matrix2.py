#!/usr/bin/env python3
"""重绘 keyboard_matrix.kicad_sch: 5x5 键矩阵, 用 R/C net label 网络(无交叉)。

每键 pin1 -> 列网络 C1..C5, pin2 -> 行网络 R1..R5。无物理总线避免交叉/未连。
"""
import json
import sys
sys.path.insert(0, "src")

from kicad_mcp.client import KiCadClient
from kicad_mcp.tools.schematic import (
    _sch_context, _read_symbols, kicad_sch_place_symbols_grid,
    kicad_sch_add_text, kicad_sch_add_line, kicad_sch_check_layout)
from kicad_mcp.proto.schematic import schematic_types_pb2 as st
from kicad_mcp.proto.common.types import enums_pb2 as en

MM = 10_000
ROWS, COLS = 5, 5
X0, Y0 = 70.0, 75.0


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


url, header = _sch_context()
with KiCadClient(url, client_name="mx2") as kc:
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

print("=== 1. 25 键网格 ===")
keys = [{"lib": "Switch", "entry": "SW_Push", "ref": f"K{r * COLS + c + 1}",
         "value": "SW"} for r in range(ROWS) for c in range(COLS)]
print(kicad_sch_place_symbols_grid(json.dumps(keys), columns=COLS,
                                   col_gap_mm=15.24, row_gap_mm=15.24,
                                   x0_mm=X0, y0_mm=Y0))

syms = _read_symbols()
wires, labels = [], []

print("=== 2. 每键 R/C net label ===")
for r in range(ROWS):
    for c in range(COLS):
        ref = f"K{r * COLS + c + 1}"
        pins = syms[ref]["pins"]
        p1 = pins.get("1"); p2 = pins.get("2")
        if p1:
            wires.append(wire_i(p1[0], p1[1], p1[0] - 3 * MM, p1[1]))
            labels.append(label_i(f"C{c + 1}", p1[0] - 3 * MM, p1[1]))
        if p2:
            wires.append(wire_i(p2[0], p2[1], p2[0] + 3 * MM, p2[1]))
            labels.append(label_i(f"R{r + 1}", p2[0] + 3 * MM, p2[1]))

with KiCadClient(url, client_name="mx2") as kc:
    r = kc.create_items(header, wires + labels)
    print(f"连线+标签: {len(wires) + len(labels)} ok={sum(1 for c in r.created_items if c.status.code==1)}")

print("=== 3. 边框 + 标题 + 说明 ===")
print(kicad_sch_add_line(40, 50, 230, 50, "notes"))
print(kicad_sch_add_line(40, 160, 230, 160, "notes"))
print(kicad_sch_add_line(40, 50, 40, 160, "notes"))
print(kicad_sch_add_line(230, 50, 230, 160, "notes"))
print(kicad_sch_add_text("KEYBOARD 89 - 键盘矩阵 (5x5 示意)", 135, 38, 4.0))
print(kicad_sch_add_text("完整 5x22 扫描 (89 键): 行 R1-R5 接 GPIO, 列 C1-C22", 135, 168, 2.0))
print(kicad_sch_add_text("每键串联 1N4148W 二极管防串扰 (阳极接行, 阴极接列)", 135, 180, 2.0))

print("=== 4. check_layout ===")
print(kicad_sch_check_layout())
print("完成")
