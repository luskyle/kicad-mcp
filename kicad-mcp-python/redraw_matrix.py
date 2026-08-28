#!/usr/bin/env python3
"""用新 MCP 工具绘制 keyboard_matrix.kicad_sch (5x5 键盘矩阵示意)。

展示: 键网格排布(place_symbols_grid) + 列二极管 + 行列总线(connect/wire) +
行/列网络标签。完整键盘为 5x22 扫描 (89 键), 此处以 5x5 展示连接原理。
"""
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

ROWS, COLS = 5, 5
X0, Y0 = 70.0, 75.0
GAP = 15.24

url, header = _sch_context()
with KiCadClient(url, client_name="matrix") as kc:
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

print("=== 1. 键网格排布 (25 键, place_symbols_grid) ===")
keys = [{"lib": "Switch", "entry": "SW_Push", "ref": f"K{r * COLS + c + 1}",
         "value": "SW"} for r in range(ROWS) for c in range(COLS)]
print(kicad_sch_place_symbols_grid(json.dumps(keys), columns=COLS,
                                   col_gap_mm=GAP, row_gap_mm=GAP,
                                   x0_mm=X0, y0_mm=Y0))

print("=== 2. 列二极管 (每列 1 个, 上方) ===")
diodes = [{"lib": "Diode", "entry": "1N4148W", "ref": f"D{c + 1}",
           "value": "1N4148"} for c in range(COLS)]
print(kicad_sch_place_symbols_grid(json.dumps(diodes), columns=COLS,
                                   col_gap_mm=GAP, row_gap_mm=GAP,
                                   x0_mm=X0, y0_mm=Y0 - 14))

syms = _read_symbols()
print("=== 3. 行列总线 ===")
wires = []
# 行总线: 每行上方一条水平线
row_bus_y = []
for r in range(ROWS):
    y = Y0 + r * GAP
    ky = y - 0.5 * GAP   # 行总线在键上方半格
    row_bus_y.append(ky)
    wires.append(st.Line())
    wires[-1].start.x_nm = int((X0 - 8) * MM); wires[-1].start.y_nm = int(ky * MM)
    wires[-1].end.x_nm = int((X0 + (COLS - 1) * GAP + 8) * MM); wires[-1].end.y_nm = int(ky * MM)
    wires[-1].layer = st.SL_WIRE
# 列总线: 每列左侧一条垂直线
col_bus_x = []
for c in range(COLS):
    x = X0 + c * GAP
    kx = x - 0.5 * GAP
    col_bus_x.append(kx)
    wires.append(st.Line())
    wires[-1].start.x_nm = int(kx * MM); wires[-1].start.y_nm = int((Y0 - 14) * MM)
    wires[-1].end.x_nm = int(kx * MM); wires[-1].end.y_nm = int((Y0 + (ROWS - 1) * GAP + 8) * MM)
    wires[-1].layer = st.SL_WIRE

# 每键连接: pin1(左) -> 列总线, pin2(右) -> 行总线
for r in range(ROWS):
    for c in range(COLS):
        ref = f"K{r * COLS + c + 1}"
        pins = syms[ref]["pins"]  # {num: (ix,iy)}
        p1 = pins.get("1"); p2 = pins.get("2")
        if p1:
            # pin1 -> 列总线 (水平向左)
            wires.append(st.Line())
            wires[-1].start.x_nm = int(p1[0]); wires[-1].start.y_nm = int(p1[1])
            wires[-1].end.x_nm = int(col_bus_x[c] * MM); wires[-1].end.y_nm = int(p1[1])
            wires[-1].layer = st.SL_WIRE
        if p2:
            # pin2 -> 行总线 (垂直向上)
            wires.append(st.Line())
            wires[-1].start.x_nm = int(p2[0]); wires[-1].start.y_nm = int(p2[1])
            wires[-1].end.x_nm = int(p2[0]); wires[-1].end.y_nm = int(row_bus_y[r] * MM)
            wires[-1].layer = st.SL_WIRE

with KiCadClient(url, client_name="matrix") as kc:
    r = kc.create_items(header, wires)
    print(f"总线+连接: {len(wires)} 段 ok={sum(1 for c in r.created_items if c.status.code==1)}")

print("=== 4. 行/列网络标签 + 说明 ===")
# 行标签 R1-R5 在行总线左端
for r in range(ROWS):
    print(kicad_sch_add_line(X0 - 6, row_bus_y[r], X0 - 2, row_bus_y[r], "wire"))
# 列标签 C1-C5 在列总线顶端
for c in range(COLS):
    print(kicad_sch_add_line(col_bus_x[c], Y0 - 12, col_bus_x[c], Y0 - 14 + 2, "wire"))
# 边框 + 标题 + 说明
print(kicad_sch_add_line(40, 50, 230, 50, "notes"))
print(kicad_sch_add_line(40, 160, 230, 160, "notes"))
print(kicad_sch_add_line(40, 50, 40, 160, "notes"))
print(kicad_sch_add_line(230, 50, 230, 160, "notes"))
print(kicad_sch_add_text("KEYBOARD 89 - 键盘矩阵 (5x5 示意)", 135, 38, 4.0))
print(kicad_sch_add_text("完整 5x22 扫描 (89 键): 行 R1-R5 接 GPIO, 列 C1-C22", 135, 168, 2.0))
print(kicad_sch_add_text("每键串联 1N4148W 二极管防串扰 (阳极接行, 阴极接列)", 135, 180, 2.0))

print("=== 5. check_layout ===")
print(kicad_sch_check_layout())
print("完成")
