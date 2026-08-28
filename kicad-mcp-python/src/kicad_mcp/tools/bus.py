"""L3 总线（Bus）工具：数据总线类电路绘制。

总线基础（导线 + 标签）由现有 Line(SL_BUS) / Label 实现；Bus Entry（信号线
斜接到总线的短对角线）需要 C++ patch（BusEntry proto + SCH_BUS_ENTRY_BASE
Serialize/Deserialize + TypeNameFromAny 映射），本仓库已编译进 eeschema。

工具：
- kicad_sch_add_bus        : 画总线导线
- kicad_sch_add_bus_label  : 放总线标签（如 "D[0..7]"）
- kicad_sch_add_bus_entry  : 放 Bus Entry（总线↔信号线短斜线）
- kicad_sch_connect_bus    : 一键把某个符号引脚连到水平总线（自动 entry + 竖直导线）
"""

from __future__ import annotations

from typing import Optional

from ..client import KiCadClient
from ..proto.common.types import base_types_pb2
from ..proto.schematic import schematic_types_pb2
from .schematic import (
    MM,
    _check_create_resp,
    _read_symbols,
    _sch_context,
    _snap_grid,
    kicad_sch_add_label,
    kicad_sch_add_line,
)

# Bus entry 默认对角线长（2.54mm）
DEFAULT_ENTRY_MM = 2.54


def kicad_sch_add_bus(
    x1_mm: float,
    y1_mm: float,
    x2_mm: float,
    y2_mm: float,
) -> str:
    """在原理图上画一条总线（Bus，粗线）。

    Args:
        x1_mm, y1_mm: 起点（毫米）。
        x2_mm, y2_mm: 终点（毫米）。

    说明: 端点自动吸附 1.27mm 网格（离网格的导线 KiCad 不连接）。总线标签、
    引脚连总线用 kicad_sch_add_bus_label / kicad_sch_connect_bus。
    """
    x1, y1 = _snap_grid(x1_mm), _snap_grid(y1_mm)
    x2, y2 = _snap_grid(x2_mm), _snap_grid(y2_mm)
    return kicad_sch_add_line(x1, y1, x2, y2, layer="bus")


def kicad_sch_add_bus_label(
    text: str,
    x_mm: float,
    y_mm: float,
    height_mm: float = 2.54,
) -> str:
    """在总线上放一个总线标签（如 "D[0..7]"）。

    Args:
        text: 标签文本，总线名带括号（如 "D[0..7]"）。
        x_mm, y_mm: 位置（应落在总线上；自动吸附 1.27mm 网格，保证在总线上）。
        height_mm: 字高。

    说明: 放在 bus 层导线上的 local 标签即总线标签（KiCad 自动识别），
    总线必须有名（标签落在总线上）才能让信号线成为其成员。
    """
    x, y = _snap_grid(x_mm), _snap_grid(y_mm)
    return kicad_sch_add_label("local", text, x, y, height_mm)


def kicad_sch_add_bus_entry(
    x_mm: float,
    y_mm: float,
    end_x_mm: float,
    end_y_mm: float,
) -> str:
    """放一个 Bus Entry（总线↔信号线的短斜线连接）。

    Args:
        x_mm, y_mm: 总线侧端点（应落在总线上）。
        end_x_mm, end_y_mm: 导线侧端点（信号线接到这里）。

    说明: 需要已打 BusEntry patch 并重新编译的 eeschema。
    """
    entry = schematic_types_pb2.BusEntry()
    entry.position.x_nm = round(x_mm * MM)
    entry.position.y_nm = round(y_mm * MM)
    entry.end.x_nm = round(end_x_mm * MM)
    entry.end.y_nm = round(end_y_mm * MM)

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [entry])
    _check_create_resp(resp)
    return (f"已放置 Bus Entry: ({x_mm},{y_mm})mm(总线侧) -> "
            f"({end_x_mm},{end_y_mm})mm(导线侧)")


def kicad_sch_connect_bus(
    ref: str,
    pin_number: str,
    bus_y_mm: float,
    entry_offset_mm: float = DEFAULT_ENTRY_MM,
    signal: str = "",
) -> str:
    """把符号的某个引脚连接到一条水平总线（自动放 Bus Entry + 竖直导线）。

    总线应为水平线（y=bus_y_mm）。工具读取引脚精确坐标，在引脚正上方/下方
    放一个 Bus Entry（总线侧落在总线上、导线侧正对引脚），再用竖直导线把
    引脚连到 entry 的导线侧。

    Args:
        ref: 符号 Reference（如 "U1"）。
        pin_number: 引脚号（如 "1"、"A0"）。
        bus_y_mm: 水平总线的 y 坐标（自动吸附 1.27mm 网格）。
        entry_offset_mm: Bus Entry 对角线长（默认 2.54，保持网格对齐）。
        signal: 可选，该信号线对应的总线成员名（如总线 "D[0..2]" 的成员 "D0"）。
            会在导线上放同名 local 标签，使其成为总线成员（否则 ERC 报
            "graphically connected to bus but not a member"）。

    Returns:
        放置摘要。
    """
    syms = _read_symbols()
    info = syms.get(ref)
    if not info:
        raise RuntimeError(f"没有已放置符号 {ref}（当前有: {sorted(syms)}）")
    pins = info.get("pins") or {}
    if str(pin_number) not in pins:
        raise RuntimeError(f"符号 {ref} 没有引脚 {pin_number}（可用: {sorted(pins)}）")
    px_iu, py_iu = pins[str(pin_number)]
    px_mm, py_mm = px_iu / MM, py_iu / MM

    # 总线 y 吸附 1.27mm 网格（否则 entry/导线离网格，KiCad 不连接）
    bus_y = _snap_grid(bus_y_mm)
    offset = round(_snap_grid(entry_offset_mm) / 1.27) * 1.27  # 保持 1.27 整数倍

    # Bus Entry 方向：引脚在总线下方则斜向下，上方则斜向上
    if py_mm > bus_y:
        wire_end_y = bus_y + offset
    else:
        wire_end_y = bus_y - offset
    # 总线侧端点：从引脚 x 横向偏移，落在总线上
    bus_side_x = px_mm + offset
    bus_side_y = bus_y
    wire_end_x = px_mm

    entry_msg = kicad_sch_add_bus_entry(bus_side_x, bus_side_y,
                                        wire_end_x, wire_end_y)
    wire_msg = kicad_sch_add_line(px_mm, py_mm, wire_end_x, wire_end_y, "wire")

    # 信号标签：放在导线上（引脚与 entry 之间的中点附近），使其成为总线成员
    signal_msg = ""
    if signal.strip():
        ly = (py_mm + wire_end_y) / 2
        kicad_sch_add_label("local", signal.strip(), px_mm, ly)
        signal_msg = f"\n  信号标签 '{signal}' @({px_mm:.2f},{ly:.2f})mm"

    return (f"已连接 {ref}.{pin_number} ({px_mm:.2f},{py_mm:.2f})mm -> 总线 "
            f"(y={bus_y:.2f}mm)\n  {entry_msg}\n  {wire_msg}{signal_msg}")


ALL_TOOLS = [
    kicad_sch_add_bus,
    kicad_sch_add_bus_label,
    kicad_sch_add_bus_entry,
    kicad_sch_connect_bus,
]
