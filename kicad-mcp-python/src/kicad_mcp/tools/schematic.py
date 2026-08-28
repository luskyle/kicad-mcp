"""KiCad MCP 原理图工具：创建/查询/更新/删除原理图元素。

⚠️ 这些工具依赖 KiCad 源码补丁（见仓库 PATCH 说明：SchematicLayer 枚举、
TypeNameFromAny schematic 映射、SCH_TEXT/SCH_SYMBOL/Label 序列化、符号库加载、
GetItems/SaveDocument handler、多元素创建修复）。
未打补丁的 KiCad 10.0.5 上，创建原理图元素会导致 eeschema 段错误崩溃！
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .. import symbols as symbols_mod
from .. import spice as spice_mod
from ..client import (
    DOCTYPE_SCHEMATIC,
    KiCadClient,
    find_document_socket,
)
from ..proto.common.commands import editor_commands_pb2
from ..proto.common.types import base_types_pb2, enums_pb2
from ..proto.schematic import schematic_types_pb2
from ..symbols import absolute_pin, get_pins# 原理图内部单位: SCH_IU_PER_MM = 1e4 (1 IU = 100nm)。KiCad API 的 x_nm 字段
# 实际存的就是内部 IU（PackVector2/UnpackVector2 不做单位换算），因此原理图
# 坐标换算 1mm = 1e4，而不是 PCB 的 1e6（PCB_IU_PER_MM = 1e6）。
MM = 10_000

# 元素类型名 -> KiCadObjectType 枚举（GetItems 查询用）
KOT_MAP = {
    "text": enums_pb2.KOT_SCH_TEXT,
    "symbol": enums_pb2.KOT_SCH_SYMBOL,
    "line": enums_pb2.KOT_SCH_LINE,
    "local_label": enums_pb2.KOT_SCH_LABEL,
    "global_label": enums_pb2.KOT_SCH_GLOBAL_LABEL,
    "hier_label": enums_pb2.KOT_SCH_HIER_LABEL,
    "directive_label": enums_pb2.KOT_SCH_DIRECTIVE_LABEL,
    "shape": enums_pb2.KOT_SCH_SHAPE,
    "image": enums_pb2.KOT_SCH_BITMAP,
    "no_connect": enums_pb2.KOT_SCH_NO_CONNECT,
    "junction": enums_pb2.KOT_SCH_JUNCTION,
}

LABEL_TYPE_MAP = {
    "global": schematic_types_pb2.GlobalLabel,
    "local": schematic_types_pb2.LocalLabel,
    "hier": schematic_types_pb2.HierarchicalLabel,
    "directive": schematic_types_pb2.DirectiveLabel,
}


def _sch_context() -> tuple:
    url, docs = find_document_socket(DOCTYPE_SCHEMATIC)
    if url is None:
        raise RuntimeError(
            "没有可用的原理图进程。请先启动 KiCad 的 eeschema 并打开一个 .kicad_sch 文件。"
        )
    header = base_types_pb2.ItemHeader()
    header.document.CopyFrom(docs[0])
    return url, header


def _snap_grid(v_mm: float, grid_mm: float = 1.27) -> float:
    """把毫米坐标吸附到标准网格（默认 1.27mm），保证引脚落在 ERC 连接网格上。"""
    return round(v_mm / grid_mm) * grid_mm


def _current_sch_path() -> str:
    """从当前打开的 eeschema 文档推断 .kicad_sch 完整路径。"""
    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        docs = kc.get_open_documents(DOCTYPE_SCHEMATIC)
    if not docs:
        raise RuntimeError("当前没有打开的 .kicad_sch 文档")
    doc = docs[0]
    fname = doc.board_filename or ""
    proj_path = doc.project.path if doc.project and doc.project.path else ""
    if proj_path:
        return str(Path(proj_path) / fname)
    return fname


def _find_kicad_cli() -> str:
    """定位 kicad-cli：优先环境变量，其次常见编译路径，最后 PATH。"""
    env = os.environ.get("KICAD_CLI")
    if env:
        return env
    candidates = [
        "/media/luskyle/DATA/project/kicad-mcp/build/kicad/kicad-cli",
        "/usr/local/bin/kicad-cli",
        "/usr/bin/kicad-cli",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "kicad-cli"


def _check_create_resp(resp) -> None:
    if resp.status != 1:
        raise RuntimeError(f"KiCad 返回整体状态码 {resp.status}")
    for ci in resp.created_items:
        if ci.status.code != 1:
            raise RuntimeError(
                f"创建元素失败 (code={ci.status.code}): {ci.status.error_message}"
            )


def kicad_sch_add_text(
    text: str,
    x_mm: float,
    y_mm: float,
    height_mm: float = 2.54,
) -> str:
    """在原理图上创建一个文本注释（SCH_TEXT）。

    Args:
        text: 文本内容。
        x_mm, y_mm: 文本位置（毫米）。
        height_mm: 字高（毫米）。

    注意: 需要已打补丁的 KiCad（10.0.5 会崩溃）。
    """
    sch_text = schematic_types_pb2.Text()
    sch_text.text.position.x_nm = int(x_mm * MM)
    sch_text.text.position.y_nm = int(y_mm * MM)
    sch_text.text.attributes.size.x_nm = int(height_mm * MM)
    sch_text.text.attributes.size.y_nm = int(height_mm * MM)
    sch_text.text.text = text

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [sch_text])

    _check_create_resp(resp)
    return f"已在原理图 ({x_mm}mm, {y_mm}mm) 创建文本 '{text}'"


def kicad_sch_add_line(
    x1_mm: float,
    y1_mm: float,
    x2_mm: float,
    y2_mm: float,
    layer: str = "wire",
) -> str:
    """在原理图上创建一条连线/图形线（SCH_LINE）。

    Args:
        x1_mm, y1_mm: 起点（毫米）。
        x2_mm, y2_mm: 终点（毫米）。
        layer: 层，"wire" | "bus" | "notes"。

    注意: 需要已打补丁的 KiCad（10.0.5 会崩溃）。
    """
    layers = {"wire": schematic_types_pb2.SL_WIRE,
              "bus": schematic_types_pb2.SL_BUS,
              "notes": schematic_types_pb2.SL_NOTES}
    if layer.lower() not in layers:
        raise ValueError(f"不支持的层: {layer}，可选: {sorted(layers)}")

    line = schematic_types_pb2.Line()
    # 用 round 而非 int：ix/MM*MM 的浮点误差若用 int 截断会差 1 IU，
    # KiCad 网格连接判定会把线端点判为不与引脚相连（ERC pin_not_connected）
    line.start.x_nm = round(x1_mm * MM)
    line.start.y_nm = round(y1_mm * MM)
    line.end.x_nm = round(x2_mm * MM)
    line.end.y_nm = round(y2_mm * MM)
    line.layer = layers[layer.lower()]

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [line])

    _check_create_resp(resp)
    return (
        f"已在原理图 {layer} 层创建连线: ({x1_mm},{y1_mm})mm -> ({x2_mm},{y2_mm})mm"
    )


def kicad_sch_add_symbol(
    lib_nickname: str,
    entry_name: str,
    x_mm: float,
    y_mm: float,
    reference: Optional[str] = None,
    value: Optional[str] = None,
    orientation_degrees: int = 0,
    snap_to_grid: bool = True,
    avoid_overlap: bool = True,
) -> str:
    """在原理图上放置一个符号（SCH_SYMBOL）。

    Args:
        lib_nickname: 符号库昵称（如 "Device"）。
        entry_name: 符号名（如 "R" / "C"）。
        x_mm, y_mm: 符号位置（毫米）。
        reference: 可选，参考位号（如 "R1"）。
        value: 可选，值（如 "10k"）。
        orientation_degrees: 旋转角度（0/90/180/270，默认 0）。
        snap_to_grid: 是否把中心吸附到 1.27mm 网格（默认 True）。
            标准 KiCad 符号的引脚都在 1.27mm 网格上，中心在网格上时引脚也
            在网格上，ERC 才不会报 "off connection grid"。
        avoid_overlap: 放置前检测是否与现有符号重叠（默认 True）。
            重叠时会报错提示，避免元件叠在一起。

    注意: 需要已打补丁的 KiCad（10.0.5 会崩溃）。
    """
    if snap_to_grid:
        x_mm = _snap_grid(x_mm)
        y_mm = _snap_grid(y_mm)

    # 防重叠: 与已放置符号的包围盒比较
    if avoid_overlap:
        new_bbox = _symbol_abs_bbox_mm(lib_nickname, entry_name, x_mm, y_mm,
                                       orientation_degrees)
        existing = _read_symbols()
        for ref, info in existing.items():
            if _bbox_overlap(new_bbox, _symbol_bbox_mm(info)):
                raise RuntimeError(
                    f"放置位置 ({x_mm:.1f},{y_mm:.1f})mm 与现有符号 {ref} 重叠！\n"
                    f"请调整位置，或使用 kicad_sch_place_symbols_grid 自动网格排布"
                )

    symbol = schematic_types_pb2.Symbol()
    symbol.position.x_nm = round(x_mm * MM)
    symbol.position.y_nm = round(y_mm * MM)
    symbol.lib_id.library_nickname = lib_nickname
    symbol.lib_id.entry_name = entry_name
    symbol.orientation_degrees = int(orientation_degrees)
    if reference:
        f = symbol.fields.add()
        f.name = "Reference"
        f.value = reference
    if value:
        f = symbol.fields.add()
        f.name = "Value"
        f.value = value

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [symbol])

    _check_create_resp(resp)

    # 计算每个引脚的绝对坐标（含旋转），供后续连线使用
    pins = get_pins(lib_nickname, entry_name)
    orient = int(orientation_degrees) % 360
    pin_parts = []
    for p in pins:
        ax, ay = absolute_pin(x_mm, y_mm, orient, p)
        pin_parts.append(f"{p.number}({p.name})@({ax:.2f},{ay:.2f})")

    msg = (
        f"已放置 {lib_nickname}:{entry_name} ref={reference or '?'} @({x_mm:.1f},{y_mm:.1f})mm"
        + (f" 旋转{orientation_degrees}°" if orientation_degrees else "")
    )
    if pin_parts:
        msg += "\n  引脚: " + " | ".join(pin_parts)
    return msg


def _read_symbols() -> dict:
    """读回原理图中所有符号：{reference: {lib, entry, pos_mm, orientation, pins}}。

    pins 是 KiCad 计算出的每个引脚绝对位置（IU 整数），用于精确连线。
    """
    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        got = kc.get_items(header, [KOT_MAP["symbol"]])
    out = {}
    for a in got.items:
        if not a.Is(schematic_types_pb2.Symbol.DESCRIPTOR):
            continue
        s = schematic_types_pb2.Symbol()
        a.Unpack(s)
        fields = {f.name: f.value for f in s.fields}
        ref = fields.get("Reference", "")
        if not ref:
            continue
        pins = {}
        for p in s.pins:
            pins[p.number] = (p.position.x_nm, p.position.y_nm)
        out[ref] = {
            "lib": s.lib_id.library_nickname,
            "entry": s.lib_id.entry_name,
            "x_mm": s.position.x_nm / MM,
            "y_mm": s.position.y_nm / MM,
            "orientation": s.orientation_degrees,
            "pins": pins,
        }
    return out


# ============================================================
# 布局辅助: 页面尺寸 / 符号包围盒 / 重叠检测
# ============================================================

# KiCad 标准图纸尺寸 (宽, 高) mm
_PAPER_MM = {
    "A0": (1189, 841), "A1": (841, 594), "A2": (594, 420),
    "A3": (420, 297), "A4": (297, 210), "A5": (210, 148),
    "A": (279.4, 215.9), "B": (431.8, 279.4), "C": (558.8, 431.8),
    "D": (863.6, 558.8), "E": (1117.6, 863.6),
}

# 建议预留边距 (mm), 避免元素贴边/出界
PAGE_MARGIN_MM = 15.0

# 符号包围盒 padding: 引脚延伸 2.54 + 安全间隙 1.27
_BBOX_PAD_MM = 2.54 + 1.27


def _sheet_size_mm(sch_file: Optional[str] = None) -> tuple:
    """读取 .kicad_sch 图纸尺寸 (宽, 高) mm; 默认 A4 297x210。"""
    path = sch_file or _current_sch_path()
    try:
        txt = Path(path).read_text(errors="ignore")
        m = re.search(r'\(paper "([^"]+)"', txt)
        if m:
            name = m.group(1).upper()
            if name in _PAPER_MM:
                return _PAPER_MM[name]
        m2 = re.search(r'\(size ([0-9.]+) ([0-9.]+)', txt)
        if m2:
            return float(m2.group(1)), float(m2.group(2))
    except Exception:
        pass
    return (297.0, 210.0)


def _symbol_bbox_mm(info: dict) -> tuple:
    """符号占用包围盒 (min_x, min_y, max_x, max_y) mm, 基于引脚绝对位置。

    info 来自 _read_symbols(): 含 x_mm/y_mm 和 pins{num:(x_iu,y_iu)}。
    """
    pins = info.get("pins") or {}
    if not pins:
        x, y = info["x_mm"], info["y_mm"]
        return (x - 5, y - 5, x + 5, y + 5)
    xs = [p[0] / MM for p in pins.values()]
    ys = [p[1] / MM for p in pins.values()]
    return (min(xs) - _BBOX_PAD_MM, min(ys) - _BBOX_PAD_MM,
            max(xs) + _BBOX_PAD_MM, max(ys) + _BBOX_PAD_MM)


def _bbox_overlap(a: tuple, b: tuple) -> bool:
    """两个 (min_x, min_y, max_x, max_y) 包围盒是否相交。"""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _symbol_abs_bbox_mm(lib_nickname: str, entry_name: str, x_mm: float, y_mm: float,
                        orientation_degrees: int = 0) -> tuple:
    """新放置符号的绝对包围盒 mm (从符号库引脚计算)。"""
    pins = get_pins(lib_nickname, entry_name)
    if not pins:
        return (x_mm - 5, y_mm - 5, x_mm + 5, y_mm + 5)
    orient = int(orientation_degrees) % 360
    abs_pins = [absolute_pin(x_mm, y_mm, orient, p) for p in pins]
    xs = [a[0] for a in abs_pins]
    ys = [a[1] for a in abs_pins]
    return (min(xs) - _BBOX_PAD_MM, min(ys) - _BBOX_PAD_MM,
            max(xs) + _BBOX_PAD_MM, max(ys) + _BBOX_PAD_MM)


def kicad_sch_get_symbol_pins(reference: str) -> str:
    """查询已放置符号的引脚绝对坐标（考虑旋转），供精确连线。

    Args:
        reference: 符号的 Reference（如 "R1"、"BAT1"）。
    """
    syms = _read_symbols()
    if reference not in syms:
        raise RuntimeError(f"未找到符号 ref={reference}（当前图中有: {sorted(syms)}）")
    info = syms[reference]
    pins = info.get("pins") or {}
    if not pins:
        return f"符号 {reference} 无引脚信息"
    lines = [f"{reference} ({info['lib']}:{info['entry']}) @({info['x_mm']:.1f},{info['y_mm']:.1f})mm 旋转{info['orientation']}°"]
    for num, (ix, iy) in sorted(pins.items()):
        lines.append(f"  引脚 {num} = ({ix / MM:.2f}, {iy / MM:.2f})mm")
    return "\n".join(lines)


def kicad_sch_connect(
    ref_a: str,
    pin_a: str,
    ref_b: str,
    pin_b: str,
    via_x_mm: Optional[float] = None,
    via_y_mm: Optional[float] = None,
    auto_avoid: bool = True,
) -> str:
    """连接两个符号的引脚（自动对齐引脚坐标，画直角折线）。

    这是引脚感知的连线：读取 KiCad 计算的每个引脚绝对位置（与符号库引脚
    偏移、旋转完全一致），把 wire 端点精确落在引脚上；走线为直角折线
    （Z 形，可选 via 点控制轨道位置）。

    Args:
        ref_a / pin_a: 起点符号的 Reference 与引脚号（如 "BAT1","1"）。
        ref_b / pin_b: 终点符号的 Reference 与引脚号。
        via_x_mm / via_y_mm: 可选，指定走线经过的中间点，控制布线路径。
        auto_avoid: 未指定 via 时自动检测路径是否穿过其他符号，若穿过则
            选择不冲突的轨道绕行（默认 True）。
    """
    syms = _read_symbols()
    for ref in (ref_a, ref_b):
        if ref not in syms:
            raise RuntimeError(f"未找到符号 ref={ref}（当前图中有: {sorted(syms)}）")

    def pin_iu(ref, pin_no):
        pins = syms[ref].get("pins") or {}
        if str(pin_no) in pins:
            return pins[str(pin_no)]           # (iu_x, iu_y)，KiCad 精确值
        raise RuntimeError(
            f"符号 {ref} 没有引脚 {pin_no}（可用引脚: {sorted(pins)}）")

    p1 = pin_iu(ref_a, pin_a)
    p2 = pin_iu(ref_b, pin_b)

    via_ix = round(via_x_mm * MM) if via_x_mm is not None else None
    via_iy = round(via_y_mm * MM) if via_y_mm is not None else None

    note = ""
    if auto_avoid and via_ix is None and via_iy is None:
        obstacles = [_symbol_bbox_mm(i) for r, i in syms.items()
                     if r not in (ref_a, ref_b)]
        segments, track = _route_avoiding(p1, p2, obstacles)
        if track is not None:
            note = f" (自动避让, 经 y={track}mm 轨道)"
    else:
        segments = _route_wire_iu(p1, p2, via_ix, via_iy)

    url, header = _sch_context()
    lines = []
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        for (x1, y1), (x2, y2) in segments:
            line = schematic_types_pb2.Line()
            line.start.x_nm = x1
            line.start.y_nm = y1
            line.end.x_nm = x2
            line.end.y_nm = y2
            line.layer = schematic_types_pb2.SL_WIRE
            resp = kc.create_items(header, [line])
            _check_create_resp(resp)
        lines.append(
            f"已连接 {ref_a}.{pin_a} ({p1[0] / MM:.2f},{p1[1] / MM:.2f}) -> "
            f"{ref_b}.{pin_b} ({p2[0] / MM:.2f},{p2[1] / MM:.2f})，"
            f"共 {len(segments)} 段{note}"
        )
    return "\n".join(lines)


def _route_wire_iu(p1, p2, via_x=None, via_y=None):
    """IU 整数版直角布线（段列表，去除退化段）。"""
    (x1, y1), (x2, y2) = p1, p2
    if via_x is not None or via_y is not None:
        mx = x1 if via_x is None else via_x
        my = y2 if via_y is None else via_y
        segs = [((x1, y1), (mx, y1)), ((mx, y1), (mx, my)),
                ((mx, my), (x2, my)), ((x2, my), (x2, y2))]
        return [s for s in segs if s[0] != s[1]]
    if y1 == y2:
        return [((x1, y1), (x2, y2))]
    if x1 == x2:
        return [((x1, y1), (x2, y2))]
    return [((x1, y1), (x2, y1)), ((x2, y1), (x2, y2))]


def _seg_hits_bbox(seg_iu, bbox_mm) -> bool:
    """正交线段(端点 IU) 是否与包围盒(mm)相交。"""
    (x1, y1), (x2, y2) = seg_iu
    x1 = x1 / MM; y1 = y1 / MM; x2 = x2 / MM; y2 = y2 / MM
    bx0, by0, bx1, by1 = bbox_mm
    if abs(y1 - y2) < 1e-6:      # 水平段
        if not (by0 <= y1 <= by1):
            return False
        return max(min(x1, x2), bx0) <= min(max(x1, x2), bx1)
    if abs(x1 - x2) < 1e-6:      # 垂直段
        if not (bx0 <= x1 <= bx1):
            return False
        return max(min(y1, y2), by0) <= min(max(y1, y2), by1)
    return False


def _route_avoiding(p1_iu, p2_iu, obstacles_mm, margin_mm: float = 3.0):
    """找一条不穿过任何障碍的正交走线。

    Returns: (segments_iu, track_mm 或 None)
    track_mm 非空表示用了中间水平轨道避让 (便于提示)。
    """
    (x1, y1), (x2, y2) = p1_iu, p2_iu
    candidates = []
    candidates.append((None, _route_wire_iu(p1_iu, p2_iu)))              # 先横后竖
    candidates.append((None, [((x1, y1), (x1, y2)), ((x1, y2), (x2, y2))]))  # 先竖后横
    for dy in (margin_mm, -margin_mm, 2 * margin_mm, -2 * margin_mm,
               4 * margin_mm, -4 * margin_mm):
        y_mid = round((y1 + y2) / 2) + round(dy * MM)
        segs = [((x1, y1), (x1, y_mid)), ((x1, y_mid), (x2, y_mid)),
                ((x2, y_mid), (x2, y2))]
        segs = [s for s in segs if s[0] != s[1]]
        candidates.append((y_mid, segs))
    for y_mid, segs in candidates:
        if not any(_seg_hits_bbox(s, o) for s in segs for o in obstacles_mm):
            track = round(y_mid / MM, 1) if y_mid is not None else None
            return segs, track
    return candidates[0][1], None


def _route_wire(p1, p2, via_x=None, via_y=None):
    """把两个点路由成直角折线（段列表，去除退化段）。

    默认 Z 形（先横后竖）；提供 via_x/via_y 时走四段绕行路径，可精确控制
    走线经过的轨道（例如先垂直上到 via_y 再横到 via_x 再垂直到目标）。
    """
    (x1, y1), (x2, y2) = p1, p2
    if via_x is not None or via_y is not None:
        mx = x1 if via_x is None else via_x
        my = y2 if via_y is None else via_y
        segs = [((x1, y1), (mx, y1)), ((mx, y1), (mx, my)),
                ((mx, my), (x2, my)), ((x2, my), (x2, y2))]
        # 去掉退化段（同一点）
        return [s for s in segs if abs(s[0][0] - s[1][0]) > 0.001 or abs(s[0][1] - s[1][1]) > 0.001]
    if abs(y1 - y2) < 0.001:
        return [((x1, y1), (x2, y2))]                       # 同一水平：直线
    if abs(x1 - x2) < 0.001:
        return [((x1, y1), (x2, y2))]                       # 同一垂直：直线
    # Z 形：先横到目标 x，再竖到目标 y
    return [((x1, y1), (x2, y1)), ((x2, y1), (x2, y2))]


def kicad_sch_erc(sch_file: Optional[str] = None,
                  severity: str = "error,warning") -> str:
    """对当前原理图运行 KiCad 官方 ERC（电气规则检查）。

    通过 kicad-cli 对 .kicad_sch 文件执行 ERC 并报告违规项。用于验证
    绘制结果「真正无误」：未连接引脚、悬空线头、引脚/线端偏离连接网格等
    都会被检查出来。

    Args:
        sch_file: 原理图 .kicad_sch 路径；不传则使用当前 eeschema 打开的文档。
                  （建议先调用 kicad_save_document 保存，再运行 ERC。）
        severity: 报告级别，逗号分隔: error / warning / exclusion。

    Returns:
        ERC 结果文本；无违规返回 "ERC 通过"。
    """
    if not sch_file:
        sch_file = _current_sch_path()
    if not os.path.exists(sch_file):
        raise RuntimeError(f"原理图文件不存在: {sch_file}")

    kicad_cli = _find_kicad_cli()

    # 隔离 conda 环境 + 指向资源目录（与运行 eeschema 一致）
    env = dict(os.environ)
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    for k in ("CONDA_PREFIX", "CONDA_DEFAULT_ENV", "PYTHONHOME", "PYTHONPATH"):
        env.pop(k, None)
    env.setdefault("KICAD_STOCK_DATA_HOME", "/tmp/squashfs-root/share/kicad")

    tmp = tempfile.mktemp(suffix=".json")
    try:
        proc = subprocess.run(
            [kicad_cli, "sch", "erc", "--format", "json", "--severity-all",
             sch_file, "-o", tmp],
            capture_output=True, text=True, env=env, timeout=180,
        )
        if not os.path.exists(tmp):
            return (f"ERC 运行失败 (exit {proc.returncode}): "
                    f"{(proc.stderr or proc.stdout).strip()[:400]}")
        data = json.load(open(tmp, encoding='utf-8'))
    except Exception as exc:
        return f"ERC 运行异常: {exc}"
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    violations = []
    for sheet in data.get("sheets", []):
        violations += sheet.get("violations", [])

    sev_set = {s.strip().lower() for s in severity.split(",")}
    errs = [v for v in violations if v.get("severity", "").lower() in sev_set]

    if not errs:
        return "✅ ERC 通过：无违规项"

    lines = [f"❌ ERC 发现 {len(errs)} 条违规："]
    for v in errs:
        sev = v.get("severity", "?")
        desc = v.get("description", "")
        items = v.get("items", [])
        loc = items[0].get("description", "") if items else ""
        lines.append(f"  [{sev}] {desc}")
        if loc:
            lines.append(f"        -> {loc}")
    return "\n".join(lines)


def kicad_sch_simulate(
    sch_file: Optional[str] = None,
    vectors: str = "auto",
    points: int = 200,
    extra: str = "",
    auto_directive: bool = True,
) -> str:
    """对原理图进行 SPICE 电路仿真（用 KiCad 自带 ngspice 验证电路行为）。

    流程：kicad-cli 导出 SPICE netlist -> 清洗（去除 power 符号占位行、
    把 GND 网络映射为节点 0）-> libngspice 执行仿真（自动执行原理图中的
    .tran/.dc/.op 指令）-> 读取各节点电压/电流波形并做统计。

    Args:
        sch_file: 原理图 .kicad_sch 路径；不传则使用当前 eeschema 打开的文档。
                  （建议先调用 kicad_save_document 保存。）
        vectors: 观测向量。默认 "auto"：自动从 netlist 提取所有非地节点
                 生成 v(节点) 向量。也可手动指定，如 "v(/VIN),v(/OUT)"。
        points: 每个向量返回的降采样点数（默认 200，便于展示波形）。
        extra: 额外注入的 ngspice 指令，用分号分隔。例如
               " .ic v(/OUT)=0 " 让电容从 0V 开始充电；
               " .tran 1u 20m UIC " 用初始条件做瞬态。

    Returns:
        仿真摘要：器件/节点信息、各向量初值/末值/最值统计和降采样波形。
    """
    from . import common as common_mod

    if not sch_file:
        sch_file = _current_sch_path()
    if not os.path.exists(sch_file):
        raise RuntimeError(f"原理图文件不存在: {sch_file}")

    netlist = spice_mod.export_spice_netlist(sch_file)

    # 观测向量（先按 ngspice 视角清洗：GND->0、删 power 占位行）
    clean_view = spice_mod.preprocess_netlist(netlist)
    if vectors.strip() and vectors.strip().lower() != "auto":
        vec_list = [v.strip() for v in vectors.split(",") if v.strip()]
    else:
        nodes = spice_mod.extract_nodes(clean_view)
        vec_list = [f"v({n})" for n in nodes]
    if not vec_list:
        raise RuntimeError("无法确定观测向量，请手动指定 vectors=，如 'v(/VIN),v(/OUT)'")

    # 额外指令
    extra_lines = [e.strip() for e in extra.split(";") if e.strip()] if extra else None

    # 若原理图没有仿真指令且未手动指定，自动根据电路推荐并注入
    auto_injected = None
    if not extra_lines and auto_directive:
        det = spice_mod.detect_simulation(netlist)
        if not det["has_directive"] and det["recommendation"]:
            rec = det["recommendation"]
            auto_injected = rec["command"]
            # 多条指令（如 .op\n.dc）分号分隔注入
            extra_lines = [l.strip() for l in rec["command"].split("\n") if l.strip()]

    result = spice_mod.run_ngspice(netlist, vec_list, extra_lines)

    nrows = result["rows"]
    lines = [f"🧪 SPICE 仿真完成（{nrows} 个数据点）"]
    lines.append(f"   观测向量: {', '.join(vec_list)}")
    if auto_injected:
        lines.append(f"   🤖 已按电路自动选择仿真类型，注入指令: {auto_injected}")
    if extra_lines:
        lines.append(f"   注入指令: {'; '.join(extra_lines)}")

    for v in vec_list:
        series = result["vectors"][v]["data"]
        times = result["vectors"][v]["time"]
        st = spice_mod.stats_for(series)
        if not st:
            continue
        lines.append(f"\n  ▸ {v}: 初值={st['initial']:.4g}  末值={st['final']:.4g}  "
                     f"min={st['min']:.4g}  max={st['max']:.4g}  avg={st['avg']:.4g}")
        # 降采样波形
        n = len(series)
        step = max(1, n // points)
        samples = [f"{times[i]:.4g}:{series[i]:.4g}" for i in range(0, n, step)]
        # 压缩为多行，每行 6 个采样
        lines.append(f"    波形 [{v}]:")
        row = []
        for s in samples:
            row.append(s)
            if len(row) == 6:
                lines.append("       " + "  ".join(row))
                row = []
        if row:
            lines.append("       " + "  ".join(row))

    return "\n".join(lines)


def kicad_sch_detect_simulation(
    sch_file: Optional[str] = None,
) -> str:
    """分析电路并自动确定最合适的仿真类型（SPICE 分析类型）。

    根据电路拓扑自动判断该用哪种仿真：
      - 含 AC 激励源        → 交流小信号分析 `.ac`（频响/增益/带宽）
      - 正弦/调频源         → 瞬态分析 `.tran`（时域波形）
      - 脉冲/阶跃激励        → 瞬态分析 `.tran`（看响应）
      - 电容/电感 + 直流源   → 瞬态分析 `.tran`（充放电/阶跃响应）
      - 二极管/晶体管        → 直流扫描 `.dc` / 工作点 `.op`
      - 纯电阻 + 直流源      → 工作点 `.op`

    Args:
        sch_file: 原理图 .kicad_sch 路径；不传则使用当前 eeschema 打开的文档。

    Returns:
        电路元件清单、激励源类型、已有的仿真指令，以及推荐的仿真类型和指令。
    """
    sch = sch_file or _current_sch_path()
    netlist = spice_mod.export_spice_netlist(sch)
    det = spice_mod.detect_simulation(netlist)

    lines = ["📋 电路分析："]
    if det["devices_summary"]:
        lines.append("  ▸ 元件: " + ", ".join(det["devices_summary"]))
    if det["sources"]:
        src_desc = ", ".join(
            f"{s['ref']}={s['type']}{(' ' + s['value']) if s['value'] else ''}"
            for s in det["sources"])
        lines.append("  ▸ 激励: " + src_desc)
    else:
        lines.append("  ▸ 激励: （未检测到独立源）")

    if det["existing"]:
        lines.append("  ▸ 已有仿真指令: " + ", ".join(det["existing"]))
        lines.append("  → 将直接使用现有指令进行仿真")
        return "\n".join(lines)

    rec = det["recommendation"]
    if rec:
        lines.append(f"\n🧭 推荐仿真类型: {rec['type']}")
        for r in rec["reasons"]:
            lines.append(f"    · {r}")
        lines.append(f"  建议指令: {rec['command']}")
    else:
        lines.append("\n（无法确定推荐仿真类型）")

    return "\n".join(lines)


def _add_directive_text(text: str, sch_file: Optional[str]) -> None:
    """把 SPICE 仿真指令文本（以 . 开头）写入原理图空白处并保存。

    供 KiCad 内置仿真器识别（它从原理图 .tran/.op 等文本读取仿真指令）。
    """
    # 放在 A4 右下角空白处，避免与元件/连线重叠
    kicad_sch_add_text(text=text, x_mm=230.0, y_mm=50.0, height_mm=2.54)
    from .common import kicad_save_document
    try:
        kicad_save_document()
    except Exception:
        pass  # 保存失败不阻塞（KiCad 内存里已加入指令文本）


def kicad_sch_simulate_gui(
    signal: str = "",
    signals: str = "auto",
    sch_file: Optional[str] = None,
    analyze: bool = True,
    auto_directive: bool = True,
) -> str:
    """在 KiCad 集成的仿真 GUI 中运行当前原理图的 SPICE 仿真并自动显示波形。

    打开 eeschema 自带的仿真器（ngspice 集成 + 波形绘图），自动从原理图读取
    仿真指令（如 `.tran 1u 20m`）并运行。**关键信号会自动添加到波形图并显示**
    （默认自动提取所有非地电压节点，如 v(/OUT)、v(/VIN)），无需手动在 GUI 勾选。
    同时会再做一次独立仿真并**自动分析**结果（初/末/极值、充放电/振荡分类、
    时间常数估计），用于验证 GUI 波形是否合理。

    若原理图**没有仿真指令**且 auto_directive=True，会自动根据电路拓扑推断
    最合适的仿真类型（.tran/.op/.dc/.ac）并把指令文本写入原理图后再运行。

    前提:
        - 原理图包含仿真元件（Simulation_SPICE 库的源 + 带 SPICE 模型的 R/C/L/…）。
        - 建议先用 kicad_save_document 保存，再用 kicad_sch_erc 确认无误。

    Args:
        signal: 单个要显示的信号（如 "v(/OUT)"）。与 signals 二选一。
        signals: 要在波形图中自动显示的信号，逗号分隔（如 "v(/OUT),v(/VIN)"）；
                "auto"（默认）自动提取所有非地电压节点。
        sch_file: 原理图路径；不传则使用当前 eeschema 打开的文档。
        analyze: 是否自动分析仿真结果并验证（默认 True）。
        auto_directive: 原理图无仿真指令时，自动推荐并写入指令（默认 True）。

    Returns:
        消息 + 自动分析的结论（波形已显示在 KiCad GUI 中）。
    """
    url, header = _sch_context()
    if sch_file:
        if not os.path.exists(sch_file):
            raise RuntimeError(f"原理图文件不存在: {sch_file}")

    sch = sch_file or _current_sch_path()
    netlist = spice_mod.export_spice_netlist(sch)

    # 若原理图没有仿真指令，自动根据电路推荐并写入指令文本
    auto_dir_text = None
    if auto_directive:
        det = spice_mod.detect_simulation(netlist)
        if not det["has_directive"] and det["recommendation"]:
            auto_dir_text = det["recommendation"]["command"]
            # 取第一条指令写入原理图（如 .op / .dc 取 .op；GUI 仿真器需要指令文本）
            first_line = auto_dir_text.split("\n")[0]
            _add_directive_text(first_line, sch_file)
            netlist = spice_mod.export_spice_netlist(sch)

    # 确定要在 GUI 中自动显示的信号
    if signal and signals == "auto":
        vec_list = [signal]
    elif signals.strip() and signals.strip().lower() != "auto":
        vec_list = [s.strip() for s in signals.split(",") if s.strip()]
    else:
        clean = spice_mod.preprocess_netlist(netlist)
        nodes = spice_mod.extract_nodes(clean)
        vec_list = [f"v({n})" for n in nodes]

    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.simulate(header.document, "", vec_list)

    if not resp.success:
        raise RuntimeError(resp.message)

    lines = [resp.message,
             f"   已在波形图中自动显示: {', '.join(vec_list)}"]
    if auto_dir_text:
        lines.append(f"   🤖 原理图无仿真指令，已自动添加: {auto_dir_text}")

    # 独立仿真 + 自动分析（验证 GUI 结果是否合理）
    if analyze:
        try:
            sch = sch_file or _current_sch_path()
            netlist = spice_mod.export_spice_netlist(sch)
            lines += spice_mod.auto_analyze(netlist, vec_list)
            lines.append("   （以上为独立仿真数据，应与 KiCad GUI 波形一致）")
        except Exception as exc:
            lines.append(f"   ⚠️ 自动分析失败: {exc}")

    return "\n".join(lines)


# 标签箭头/连接形状映射（LABEL_FLAG_SHAPE）
LABEL_SHAPE_MAP = {
    "unspecified": schematic_types_pb2.LS_UNSPECIFIED,
    "input": schematic_types_pb2.LS_INPUT,
    "output": schematic_types_pb2.LS_OUTPUT,
    "bidirectional": schematic_types_pb2.LS_BIDIRECTIONAL,
    "bidi": schematic_types_pb2.LS_BIDIRECTIONAL,
    "tri_state": schematic_types_pb2.LS_TRISTATE,
    "tristate": schematic_types_pb2.LS_TRISTATE,
}

# 连接点方向（SPIN_STYLE: LEFT=0/UP=1/RIGHT=2/BOTTOM=3）
LABEL_SPIN_MAP = {
    "left": schematic_types_pb2.LSPIN_LEFT,
    "up": schematic_types_pb2.LSPIN_UP,
    "right": schematic_types_pb2.LSPIN_RIGHT,
    "down": schematic_types_pb2.LSPIN_DOWN,
}

# 指令标签形状（FLAG_SHAPE: DOT/CIRCLE/DIAMOND/RECTANGLE）
DIRECTIVE_SHAPE_MAP = {
    "point": schematic_types_pb2.DS_POINT,
    "circle": schematic_types_pb2.DS_CIRCLE,
    "diamond": schematic_types_pb2.DS_DIAMOND,
    "rectangle": schematic_types_pb2.DS_RECTANGLE,
}

_LABEL_SHAPE_NAME = {
    schematic_types_pb2.LS_UNSPECIFIED: "unspecified",
    schematic_types_pb2.LS_INPUT: "input",
    schematic_types_pb2.LS_OUTPUT: "output",
    schematic_types_pb2.LS_BIDIRECTIONAL: "bidirectional",
    schematic_types_pb2.LS_TRISTATE: "tri_state",
}
_LABEL_SPIN_NAME = {
    schematic_types_pb2.LSPIN_LEFT: "left",
    schematic_types_pb2.LSPIN_UP: "up",
    schematic_types_pb2.LSPIN_RIGHT: "right",
    schematic_types_pb2.LSPIN_DOWN: "down",
}
_DIRECTIVE_SHAPE_NAME = {
    schematic_types_pb2.DS_POINT: "point",
    schematic_types_pb2.DS_CIRCLE: "circle",
    schematic_types_pb2.DS_DIAMOND: "diamond",
    schematic_types_pb2.DS_RECTANGLE: "rectangle",
}


def kicad_sch_add_label(
    label_type: str,
    text: str,
    x_mm: float,
    y_mm: float,
    height_mm: float = 1.27,
    shape: str = "unspecified",
    spin: str = "left",
    directive_shape: str = "point",
) -> str:
    """在原理图上创建一个网络标签（Global/Local/Hier/Directive）。

    Args:
        label_type: 标签类型 "global" | "local" | "hier" | "directive"。
            选择规则: 跨页网络用 global（或跨层次图用 hier）；单页内部网络用
            local；ERC/仿真/PCB 属性指令用 directive。
        text: 标签文本（即网络名，如 "VCC" / "NET_A"）。
        x_mm, y_mm: 标签位置（毫米）。
        height_mm: 字高（毫米），默认 1.27mm（KiCad 标准字高）。
        shape: 连接箭头形状（仅 global/local/hier 有效），表示信号方向:
            "unspecified"（无向）| "input"（输入）| "output"（输出）|
            "bidirectional"（双向）| "tri_state"（三态）。
            默认 "unspecified"（KiCad 默认的斜杠箭头）。
        spin: 连接点方向: "left" | "up" | "right" | "down"。
            连接点应朝向导线/引脚所在方向（导线在标签右侧用 "left" 等）。
        directive_shape: 指令标签形状（仅 directive 有效，KiCad 界面叫
            "Net Flag" 形状）: "point" | "circle" | "diamond" | "rectangle"。
            例: 电源符号 PWR_FLAG 用 "point"；"非连接检查/差分对" 用
            "circle"；"仿真指令" 默认 "circle"。

    需要已打补丁的 KiCad（Label 文本/形状/方向序列化补丁）。
    """
    if label_type.lower() not in LABEL_TYPE_MAP:
        raise ValueError(f"不支持的标签类型: {label_type}，可选: {sorted(LABEL_TYPE_MAP)}")

    shape_key = shape.lower()
    if shape_key not in LABEL_SHAPE_MAP:
        raise ValueError(f"不支持的 shape: {shape}，可选: {sorted(LABEL_SHAPE_MAP)}")
    spin_key = spin.lower()
    if spin_key not in LABEL_SPIN_MAP:
        raise ValueError(f"不支持的 spin: {spin}，可选: {sorted(LABEL_SPIN_MAP)}")
    ds_key = directive_shape.lower()
    if ds_key not in DIRECTIVE_SHAPE_MAP:
        raise ValueError(f"不支持的 directive_shape: {directive_shape}，"
                         f"可选: {sorted(DIRECTIVE_SHAPE_MAP)}")

    label = LABEL_TYPE_MAP[label_type.lower()]()
    # round 避免浮点截断误差导致 label 偏离引脚/线端点 1 IU 而 dangling
    label.position.x_nm = round(x_mm * MM)
    label.position.y_nm = round(y_mm * MM)
    label.text.text.text = text
    label.text.text.position.x_nm = round(x_mm * MM)
    label.text.text.position.y_nm = round(y_mm * MM)
    label.text.text.attributes.size.x_nm = round(height_mm * MM)
    label.text.text.attributes.size.y_nm = round(height_mm * MM)
    # (kicad-mcp) 形状/方向/指令形状
    if isinstance(label, schematic_types_pb2.DirectiveLabel):
        label.directive_shape = DIRECTIVE_SHAPE_MAP[ds_key]
    else:
        label.shape = LABEL_SHAPE_MAP[shape_key]
    label.spin = LABEL_SPIN_MAP[spin_key]

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [label])

    _check_create_resp(resp)
    extra = ""
    if isinstance(label, schematic_types_pb2.DirectiveLabel):
        extra = f", 形状={ds_key}"
    else:
        extra = f", 形状={shape_key}, 方向={spin_key}"
    return (f"已在原理图 ({x_mm}mm, {y_mm}mm) 创建 {label_type} 标签 "
            f"'{text}'{extra}")


def kicad_sch_recommend_label(
    net_name: str,
    pin_type: str = "unspecified",
    cross_page: bool = False,
    hierarchical: bool = False,
    purpose: str = "net",
) -> str:
    """推荐某条网络应该使用的标签类型 / 形状 / 方向。

    原理图标签种类很多，本工具把“选哪种标签”变成确定的规则，AI 画图时按
    网络性质调用即可，避免选错类型。

    Args:
        net_name: 网络名（如 "VCC" / "SCLK" / "NET_A"）。
        pin_type: 引脚电气类型（决定连接箭头形状，仅作建议）:
            "input" | "output" | "bidirectional" | "tri_state" | "passive" |
            "unspecified"。
            可传 netlist 里该网络的驱动类型，或第一个连接引脚的电气类型。
        cross_page: 该网络是否跨原理图页面（True → 用全局标签 GlobalLabel）。
        hierarchical: 是否用于层次化设计（跨子图，True → 用层次标签）。
        purpose: 标签用途:
            "net"（普通网络）| "flag"（ERC/仿真/PCB 指令，用指令标签）|
            "diff"（差分对）| "power"（电源网络）。

    Returns:
        一行结论 + 一行 JSON，AI 可直接据此调用 kicad_sch_add_label。
    """
    # 1) 标签类型
    if purpose in ("flag", "diff", "sim"):
        label_type = "directive"
    elif hierarchical:
        label_type = "hier"
    elif cross_page:
        label_type = "global"
    else:
        label_type = "local"

    # 2) 连接箭头形状（global/local/hier 用）
    p = pin_type.lower()
    if p in ("input", "output", "bidirectional", "tri_state"):
        shape = p
    else:
        shape = "unspecified"      # passive/无方向 → 默认斜杠

    # 3) 指令标签形状（directive 用）
    if purpose == "flag":
        directive_shape = "point"       # 电源/地 PWR_FLAG 风格
    elif purpose == "diff":
        directive_shape = "diamond"     # 差分对
    elif purpose == "sim":
        directive_shape = "circle"      # 仿真指令
    else:
        directive_shape = "point"

    # 4) 连接点方向：默认朝左；网络以电源/地为主时朝上更常见，但一般由
    #    导线走向决定，这里给默认 left，AI 画图时可按实际走向改。
    spin = "left"

    lines = [
        f"网络 '{net_name}' 推荐: 类型={label_type}, 形状={shape}, "
        f"指令形状={directive_shape}, 方向={spin}",
        f"调用: kicad_sch_add_label(label_type=\"{label_type}\", text=\"{net_name}\", "
        f"shape=\"{shape}\", spin=\"{spin}\", directive_shape=\"{directive_shape}\", "
        f"x_mm=..., y_mm=...)",
    ]
    return "\n".join(lines)


_LABEL_PROTO_CLASSES = [
    schematic_types_pb2.GlobalLabel,
    schematic_types_pb2.LocalLabel,
    schematic_types_pb2.HierarchicalLabel,
    schematic_types_pb2.DirectiveLabel,
]


def kicad_sch_transform_item(
    item_id: str,
    rotate: str = "none",
    mirror: str = "none",
) -> str:
    """对原理图元素做旋转变换/镜像（等价于编辑器里的 R 旋转、X/Y 镜像）。

    支持的旋转/镜像方式（对应 KiCad 原理图编辑器的工具栏）:
      - 旋转: R（顺时针 90°）；Shift+R（逆时针 90°）。
      - 镜像: X（水平镜像，左右翻转）；Y（垂直镜像，上下翻转）。

    Args:
        item_id: 元素 KIID（符号或标签，来自 kicad_sch_get_items）。
        rotate: "cw"（顺时针 90°）| "ccw"（逆时针 90°）| "none"（不旋转）。
        mirror: "x"（水平镜像）| "y"（垂直镜像）| "none"（不镜像）。

    说明:
      - 符号: 旋转改变方向（0/90/180/270），镜像做 X/Y 轴翻转，二者可叠加。
      - 标签: 旋转改变连接点方向（left→up→right→down…）；
        水平镜像交换 left/right，垂直镜像交换 up/down。
      - 连线（wire）不可变换。

    Returns:
        变换后的元素状态。
    """
    if rotate not in ("none", "cw", "ccw"):
        raise ValueError(f"rotate 应为 none/cw/ccw，收到: {rotate}")
    if mirror not in ("none", "x", "y"):
        raise ValueError(f"mirror 应为 none/x/y，收到: {mirror}")
    if rotate == "none" and mirror == "none":
        return "未做任何变换（rotate 和 mirror 均为 none）"

    url, header = _sch_context()
    kots = [KOT_MAP["symbol"]] + [KOT_MAP["local_label"], KOT_MAP["global_label"],
                                  KOT_MAP["hier_label"], KOT_MAP["directive_label"]]
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        got = kc.get_items(header, kots)
        target = None
        for a in got.items:
            for cls in _LABEL_PROTO_CLASSES + [schematic_types_pb2.Symbol]:
                if not a.Is(cls.DESCRIPTOR):
                    continue
                obj = cls()
                a.Unpack(obj)
                if getattr(obj, "id", None) and obj.id.value == item_id:
                    target = (cls, obj)
                    break
            if target:
                break
        if target is None:
            # id 可能是前缀（前 8 位）
            for a in got.items:
                for cls in _LABEL_PROTO_CLASSES + [schematic_types_pb2.Symbol]:
                    if not a.Is(cls.DESCRIPTOR):
                        continue
                    obj = cls()
                    a.Unpack(obj)
                    if getattr(obj, "id", None) and obj.id.value.startswith(item_id):
                        target = (cls, obj)
                        break
                if target:
                    break
        if target is None:
            return f"未找到 id={item_id}（不是符号或标签，或已被删除）"

        cls, obj = target
        desc = ""

        if isinstance(obj, schematic_types_pb2.Symbol):
            if rotate == "cw":
                obj.orientation_degrees = (obj.orientation_degrees + 90) % 360
            elif rotate == "ccw":
                obj.orientation_degrees = (obj.orientation_degrees - 90) % 360
            if mirror == "x":
                obj.mirror = schematic_types_pb2.SM_X
            elif mirror == "y":
                obj.mirror = schematic_types_pb2.SM_Y
            desc = (f"符号 {obj.lib_id.library_nickname}:{obj.lib_id.entry_name} "
                    f"方向={obj.orientation_degrees}°, "
                    f"镜像={_SYMBOL_MIRROR_NAME.get(obj.mirror, obj.mirror)}")
        else:
            # 标签: 旋转 spin (LEFT=0/UP=1/RIGHT=2/DOWN=3), 镜像交换方向
            cur = obj.spin
            if rotate == "cw":
                cur = (cur + 1) % 4
            elif rotate == "ccw":
                cur = (cur - 1) % 4
            if mirror == "x":
                cur = {0: 2, 2: 0}.get(cur, cur)   # left<->right
            elif mirror == "y":
                cur = {1: 3, 3: 1}.get(cur, cur)   # up<->down
            obj.spin = cur
            desc = (f"标签 '{obj.text.text.text}' 方向={_LABEL_SPIN_NAME.get(cur, cur)}")

        resp = kc.update_items(header, [obj])
        if resp.status != 1:
            raise RuntimeError(f"KiCad 返回整体状态码 {resp.status}")
        for ui in resp.updated_items:
            if ui.status.code != 1:
                raise RuntimeError(f"更新元素失败 (code={ui.status.code}): "
                                   f"{ui.status.error_message}")
    return f"已变换 {desc}"


_SYMBOL_MIRROR_NAME = {
    schematic_types_pb2.SM_NONE: "无",
    schematic_types_pb2.SM_X: "X（水平）",
    schematic_types_pb2.SM_Y: "Y（垂直）",
}


def _fmt_any(any_item) -> str:
    """把 GetItems 返回的 Any 解包成一行可读描述。"""
    if any_item.Is(schematic_types_pb2.Text.DESCRIPTOR):
        t = schematic_types_pb2.Text()
        any_item.Unpack(t)
        return (f"Text id={t.id.value} '{t.text.text}' "
                f"@({t.text.position.x_nm / MM:.1f},{t.text.position.y_nm / MM:.1f})mm")
    if any_item.Is(schematic_types_pb2.Symbol.DESCRIPTOR):
        s = schematic_types_pb2.Symbol()
        any_item.Unpack(s)
        fields = {f.name: f.value for f in s.fields}
        mir = _SYMBOL_MIRROR_NAME.get(s.mirror, s.mirror)
        return (f"Symbol id={s.id.value} {s.lib_id.library_nickname}:{s.lib_id.entry_name} "
                f"ref={fields.get('Reference', '')} value={fields.get('Value', '')} "
                f"@({s.position.x_nm / MM:.1f},{s.position.y_nm / MM:.1f})mm "
                f"方向={s.orientation_degrees}° 镜像={mir}")
    if any_item.Is(schematic_types_pb2.Line.DESCRIPTOR):
        ln = schematic_types_pb2.Line()
        any_item.Unpack(ln)
        layer = {1: 'wire', 2: 'bus', 3: 'notes'}.get(ln.layer, str(ln.layer))
        return (f"Line id={ln.id.value} layer={layer} "
                f"({ln.start.x_nm / MM:.1f},{ln.start.y_nm / MM:.1f})->"
                f"({ln.end.x_nm / MM:.1f},{ln.end.y_nm / MM:.1f})mm")
    if any_item.Is(schematic_types_pb2.Shape.DESCRIPTOR):
        sh = schematic_types_pb2.Shape()
        any_item.Unpack(sh)
        stype = (schematic_types_pb2.ShapeType.Name(sh.shape_type)
                 if sh.shape_type else 'graphic')
        return (f"Shape id={sh.id.value} type={stype} filled={sh.filled} "
                f"@({sh.position.x_nm / MM:.1f},{sh.position.y_nm / MM:.1f})mm")
    if any_item.Is(schematic_types_pb2.NoConnect.DESCRIPTOR):
        nc = schematic_types_pb2.NoConnect()
        any_item.Unpack(nc)
        return (f"NoConnect id={nc.id.value} "
                f"@({nc.position.x_nm / MM:.1f},{nc.position.y_nm / MM:.1f})mm")
    if any_item.Is(schematic_types_pb2.Junction.DESCRIPTOR):
        jn = schematic_types_pb2.Junction()
        any_item.Unpack(jn)
        return (f"Junction id={jn.id.value} "
                f"@({jn.position.x_nm / MM:.1f},{jn.position.y_nm / MM:.1f})mm")
    if any_item.Is(schematic_types_pb2.Image.DESCRIPTOR):
        im = schematic_types_pb2.Image()
        any_item.Unpack(im)
        return (f"Image id={im.id.value} scale={im.scale} "
                f"@({im.position.x_nm / MM:.1f},{im.position.y_nm / MM:.1f})mm "
                f"({len(im.bitmap)}B png)")
    for proto_cls, kind in [
        (schematic_types_pb2.GlobalLabel, 'GlobalLabel'),
        (schematic_types_pb2.LocalLabel, 'LocalLabel'),
        (schematic_types_pb2.HierarchicalLabel, 'HierLabel'),
        (schematic_types_pb2.DirectiveLabel, 'DirectiveLabel'),
    ]:
        if any_item.Is(proto_cls.DESCRIPTOR):
            l = proto_cls()
            any_item.Unpack(l)
            extra = ""
            if isinstance(l, schematic_types_pb2.DirectiveLabel):
                extra = (f" 形状={_DIRECTIVE_SHAPE_NAME.get(l.directive_shape, l.directive_shape)}")
            else:
                extra = (f" 形状={_LABEL_SHAPE_NAME.get(l.shape, l.shape)}")
            extra += f" 方向={_LABEL_SPIN_NAME.get(l.spin, l.spin)}"
            return (f"{kind} id={l.id.value} '{l.text.text.text}' "
                    f"@({l.position.x_nm / MM:.1f},{l.position.y_nm / MM:.1f})mm{extra}")
    return f"<{any_item.type_url.split('/')[-1]}>"


def kicad_sch_get_items(item_types: str = "text,symbol,line,label") -> str:
    """查询原理图中的元素（读回现状，供规划/校验用）。

    Args:
        item_types: 逗号分隔的类型，可选: text / symbol / line / local_label /
            global_label / hier_label / directive_label；"label" 表示全部标签。

    Returns:
        每行一个元素的描述（含 KIID，供更新/删除使用）。
    """
    kots = []
    for raw in item_types.split(','):
        t = raw.strip()
        if t == "label":
            kots += [enums_pb2.KOT_SCH_LABEL, enums_pb2.KOT_SCH_GLOBAL_LABEL,
                     enums_pb2.KOT_SCH_HIER_LABEL, enums_pb2.KOT_SCH_DIRECTIVE_LABEL]
        elif t in KOT_MAP:
            kots.append(KOT_MAP[t])
    if not kots:
        raise ValueError(f"没有可用的元素类型: {item_types}")

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        got = kc.get_items(header, kots)

    lines = [_fmt_any(a) for a in got.items]
    return "\n".join(lines) if lines else "（原理图中没有匹配的元素）"


def kicad_sch_update_text(
    item_id: str,
    text: Optional[str] = None,
    x_mm: Optional[float] = None,
    y_mm: Optional[float] = None,
) -> str:
    """更新一个文本元素的内容和/或位置（按 GetItems 返回的 id）。

    Args:
        item_id: 目标文本的 KIID（来自 kicad_sch_get_items）。
        text: 新内容（不传则不改）。
        x_mm, y_mm: 新位置（不传则不改）。
    """
    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        got = kc.get_items(header, [KOT_MAP["text"]])
        for a in got.items:
            if not a.Is(schematic_types_pb2.Text.DESCRIPTOR):
                continue
            t = schematic_types_pb2.Text()
            a.Unpack(t)
            if t.id.value != item_id:
                continue
            if text is not None:
                t.text.text = text
            if x_mm is not None:
                t.text.position.x_nm = int(x_mm * MM)
            if y_mm is not None:
                t.text.position.y_nm = int(y_mm * MM)
            resp = kc.update_items(header, [t])
            for r in resp.updated_items:
                if r.status.code != 1:
                    raise RuntimeError(f"更新失败: {r.status.error_message}")
            return f"已更新文本 {item_id[:12]}"
        raise RuntimeError(f"未找到 id={item_id} 的文本元素")


def kicad_sch_delete_item(item_id: str) -> str:
    """按 KIID 删除原理图中的一个元素。

    Args:
        item_id: 元素 KIID（来自 kicad_sch_get_items）。
    """
    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.delete_items(header, [item_id])

    for r in resp.deleted_items:
        if r.id.value == item_id:
            if r.status == 1:   # IDS_OK
                return f"已删除元素 {item_id[:12]}"
            return f"删除失败: 状态 {r.status}"
    return f"未找到 id={item_id}（或已被删除）"


def _pt_nm(x_mm: float, y_mm: float) -> tuple:
    return round(x_mm * MM), round(y_mm * MM)


def _build_graphic_shape(shape_type: str, points: list, filled: bool,
                         stroke_width_nm: int) -> base_types_pb2.GraphicShape:
    """把简单形状描述转成 board 侧复用的 GraphicShape 几何。"""
    gs = base_types_pb2.GraphicShape()
    gs.attributes.stroke.width.value_nm = stroke_width_nm
    gs.attributes.stroke.style = enums_pb2.SLS_SOLID
    gs.attributes.fill.fill_type = (base_types_pb2.GFT_FILLED if filled
                                    else base_types_pb2.GFT_UNFILLED)
    st = shape_type.lower()
    if st in ("segment", "line"):
        seg = gs.segment
        seg.start.x_nm, seg.start.y_nm = _pt_nm(*points[0])
        seg.end.x_nm, seg.end.y_nm = _pt_nm(*points[1])
    elif st == "rectangle":
        r = gs.rectangle
        r.top_left.x_nm, r.top_left.y_nm = _pt_nm(*points[0])
        r.bottom_right.x_nm, r.bottom_right.y_nm = _pt_nm(*points[1])
    elif st == "circle":
        c = gs.circle
        c.center.x_nm, c.center.y_nm = _pt_nm(*points[0])
        c.radius_point.x_nm, c.radius_point.y_nm = _pt_nm(*points[1])
    elif st == "arc":
        a = gs.arc
        a.start.x_nm, a.start.y_nm = _pt_nm(*points[0])
        a.mid.x_nm, a.mid.y_nm = _pt_nm(*points[1])
        a.end.x_nm, a.end.y_nm = _pt_nm(*points[2])
    elif st == "bezier":
        b = gs.bezier
        b.start.x_nm, b.start.y_nm = _pt_nm(*points[0])
        b.control1.x_nm, b.control1.y_nm = _pt_nm(*points[1])
        b.control2.x_nm, b.control2.y_nm = _pt_nm(*points[2])
        b.end.x_nm, b.end.y_nm = _pt_nm(*points[3])
    else:
        raise ValueError(f"不支持的形状: {shape_type}，"
                         f"可选 segment/rectangle/circle/arc/bezier")
    return gs


def kicad_sch_add_shape(
    shape_type: str,
    points_mm: str,
    filled: bool = False,
    stroke_width_mm: float = 0.15,
    layer: str = "notes",
) -> str:
    """在原理图上创建图形形状（直线/矩形/圆/圆弧/贝塞尔曲线）。

    Args:
        shape_type: segment / rectangle / circle / arc / bezier。
        points_mm: 点列表（绝对坐标 mm），分号分隔，如 "10,20;30,40"。
            所需点数: segment/rectangle/circle=2, arc=3, bezier=4。
        filled: 是否填充。
        stroke_width_mm: 线宽（mm）。
        layer: "notes" | "wire" | "bus"。

    说明: 这些是图形注释元素，不参与电气连接。
    """
    try:
        points = [tuple(float(v) for v in p.split(","))
                  for p in points_mm.split(";") if p.strip()]
    except ValueError as e:
        raise ValueError(f"points_mm 格式应为 'x,y;x,y;...'，收到: {points_mm}") from e

    required = {"segment": 2, "line": 2, "rectangle": 2, "circle": 2,
                "arc": 3, "bezier": 4}
    n = required.get(shape_type.lower())
    if n is None:
        raise ValueError(f"不支持的形状: {shape_type}，可选 {sorted(required)}")
    if len(points) != n:
        raise ValueError(f"{shape_type} 需要 {n} 个点，收到 {len(points)}")

    layers = {"wire": schematic_types_pb2.SL_WIRE,
              "bus": schematic_types_pb2.SL_BUS,
              "notes": schematic_types_pb2.SL_NOTES}
    if layer.lower() not in layers:
        raise ValueError(f"不支持的层: {layer}，可选: {sorted(layers)}")

    stroke_nm = round(stroke_width_mm * MM)
    sh = schematic_types_pb2.Shape()
    sh.shape_type = schematic_types_pb2.ShapeType.ST_SEGMENT
    sh.filled = filled
    sh.stroke_width = stroke_nm
    sh.layer = layers[layer.lower()]
    sh.position.x_nm, sh.position.y_nm = _pt_nm(*points[0])
    sh.graphic.CopyFrom(_build_graphic_shape(shape_type, points, filled, stroke_nm))

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [sh])

    _check_create_resp(resp)
    return (f"已在原理图创建图形形状 {shape_type}（{points_mm}mm, "
            f"线宽 {stroke_width_mm}mm, {'填充' if filled else '不填充'}）")


def kicad_sch_add_no_connect(x_mm: float, y_mm: float) -> str:
    """在原理图上放置一个"不连接"（X）标记，用于标记未使用的引脚。

    Args:
        x_mm, y_mm: 位置（毫米）。通常放在未使用引脚的中心。

    注意: X 标记应精确落在引脚端点上才有效。
    """
    nc = schematic_types_pb2.NoConnect()
    nc.position.x_nm = round(x_mm * MM)
    nc.position.y_nm = round(y_mm * MM)

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [nc])

    _check_create_resp(resp)
    return f"已在 ({x_mm}mm, {y_mm}mm) 放置不连接标记"


def kicad_sch_add_image(
    file_path: str,
    x_mm: float,
    y_mm: float,
    scale: float = 1.0,
) -> str:
    """在原理图上放置一张 PNG 图片（常用于框图/说明图）。

    Args:
        file_path: PNG 文件路径。
        x_mm, y_mm: 图片中心位置（毫米）。
        scale: 显示缩放倍数。
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"图片不存在: {file_path}")

    img = schematic_types_pb2.Image()
    img.position.x_nm = round(x_mm * MM)
    img.position.y_nm = round(y_mm * MM)
    img.scale = scale
    img.bitmap = path.read_bytes()

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [img])

    _check_create_resp(resp)
    return f"已在 ({x_mm}mm, {y_mm}mm) 放置图片 {path.name} (scale={scale})"


def kicad_sch_get_sheet_info(sch_file: Optional[str] = None) -> str:
    """查询当前图纸尺寸和可绘图区域，以及现有元素占用的范围。

    Args:
        sch_file: 可选，.kicad_sch 文件路径（默认当前打开的图）。

    用途: 绘制前先调用，确定元素放置的边界，避免超出页面。
    """
    w, h = _sheet_size_mm(sch_file)
    syms = _read_symbols()
    xs, ys = [], []
    for info in syms.values():
        bx = _symbol_bbox_mm(info)
        xs += [bx[0], bx[2]]
        ys += [bx[1], bx[3]]
    extent = (min(xs), min(ys), max(xs), max(ys)) if xs else None
    lines = [
        f"图纸尺寸: {w:.0f} x {h:.0f} mm",
        f"建议可绘图区域 (留 {PAGE_MARGIN_MM:.0f}mm 边距): "
        f"X {PAGE_MARGIN_MM:.0f} - {w - PAGE_MARGIN_MM:.0f}, "
        f"Y {PAGE_MARGIN_MM:.0f} - {h - PAGE_MARGIN_MM:.0f}",
    ]
    if extent:
        over = []
        if extent[0] < PAGE_MARGIN_MM:
            over.append(f"X 左超界 {PAGE_MARGIN_MM - extent[0]:.1f}mm")
        if extent[2] > w - PAGE_MARGIN_MM:
            over.append(f"X 右超界 {extent[2] - (w - PAGE_MARGIN_MM):.1f}mm")
        if extent[1] < PAGE_MARGIN_MM:
            over.append(f"Y 上超界 {PAGE_MARGIN_MM - extent[1]:.1f}mm")
        if extent[3] > h - PAGE_MARGIN_MM:
            over.append(f"Y 下超界 {extent[3] - (h - PAGE_MARGIN_MM):.1f}mm")
        lines.append(
            f"当前符号范围: X {extent[0]:.1f}-{extent[2]:.1f}, "
            f"Y {extent[1]:.1f}-{extent[3]:.1f}"
        )
        lines.append("超出可绘图区域: " + ("; ".join(over) if over else "无"))
    else:
        lines.append("当前无符号")
    return "\n".join(lines)


def kicad_sch_check_layout(sch_file: Optional[str] = None) -> str:
    """检查布局质量: 符号重叠 + 是否超出页面边距。

    Args:
        sch_file: 可选，.kicad_sch 文件路径（默认当前打开的图）。

    Returns:
        报告: 哪些符号互相重叠、哪些超出页面，供规划修复。
    """
    syms = _read_symbols()
    bboxes = {ref: _symbol_bbox_mm(info) for ref, info in syms.items()}
    refs = sorted(bboxes)
    out = []
    # 重叠检测
    overlaps = []
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            if _bbox_overlap(bboxes[refs[i]], bboxes[refs[j]]):
                overlaps.append((refs[i], refs[j]))
    if overlaps:
        out.append(f"⚠ 检测到 {len(overlaps)} 处符号重叠:")
        for a, b in overlaps[:20]:
            out.append(f"   {a} <-> {b}")
    else:
        out.append("✓ 符号无重叠")
    # 超出页面
    w, h = _sheet_size_mm(sch_file)
    over = []
    for ref in refs:
        bx = bboxes[ref]
        if (bx[0] < PAGE_MARGIN_MM or bx[1] < PAGE_MARGIN_MM
                or bx[2] > w - PAGE_MARGIN_MM or bx[3] > h - PAGE_MARGIN_MM):
            over.append(ref)
    if over:
        out.append(f"⚠ {len(over)} 个符号超出页面/边距: {', '.join(over)}")
    else:
        out.append(f"✓ 所有符号在页面内 ({w:.0f}x{h:.0f}mm)")
    return "\n".join(out)


def kicad_sch_place_symbols_grid(
    symbols_json: str,
    columns: int = 4,
    col_gap_mm: float = 15.24,
    row_gap_mm: float = 12.7,
    x0_mm: float = 50.0,
    y0_mm: float = 50.0,
    snap_to_grid: bool = True,
) -> str:
    """批量把多个符号自动排成网格（吸附 1.27mm、间距充足、防重叠）。

    Args:
        symbols_json: JSON 数组，每项含 lib/entry/ref/value，如:
            '[{"lib":"Device","entry":"R","ref":"R1","value":"10k"},\n'
            ' {"lib":"Device","entry":"C","ref":"C1","value":"100nF"}]'
        columns: 每行符号数（默认 4）。
        col_gap_mm: 列间距（默认 15.24mm = 12 格）。
        row_gap_mm: 行间距（默认 12.7mm = 10 格）。
        x0_mm, y0_mm: 网格起点（默认 50,50）。
        snap_to_grid: 吸附 1.27mm 网格（默认 True）。

    Returns:
        每个符号的放置位置。
    """
    import json as _json

    try:
        syms = _json.loads(symbols_json)
    except Exception as e:
        raise ValueError(f"symbols_json 必须是 JSON 数组: {e}")
    if not isinstance(syms, list) or not syms:
        raise ValueError("symbols_json 应为非空数组")
    if columns < 1:
        raise ValueError("columns >= 1")

    # 自动间距: 按符号实际尺寸放大 col/row 间距, 确保不重叠
    # (用户给的 col_gap_mm/row_gap_mm 作为最小值)
    def _sym_size_mm(lib: str, entry: str) -> tuple:
        pins = get_pins(lib, entry)
        if not pins:
            # 本地库解析不到 (如系统库符号) -> 保守默认, 防重叠
            return 20.0, 20.0
        xs = [p.x_mm for p in pins]
        ys = [p.y_mm for p in pins]
        return (max(xs) - min(xs) + 2 * _BBOX_PAD_MM,
                max(ys) - min(ys) + 2 * _BBOX_PAD_MM)

    max_w, max_h = 10.0, 10.0
    for s in syms:
        w, h = _sym_size_mm(s.get("lib", "Device"), s.get("entry", "R"))
        max_w, max_h = max(max_w, w), max(max_h, h)
    # +2mm 安全余量, 避免符号包围盒恰好接触/边界判定重叠
    eff_col_gap = max(col_gap_mm, max_w + 2.0)
    eff_row_gap = max(row_gap_mm, max_h + 2.0)

    # 计算位置
    placed = []
    for i, s in enumerate(syms):
        col, row = i % columns, i // columns
        x = x0_mm + col * eff_col_gap
        y = y0_mm + row * eff_row_gap
        if snap_to_grid:
            x, y = _snap_grid(x), _snap_grid(y)
        placed.append((x, y, s))

    # 页面边界检查
    w, h = _sheet_size_mm()
    over = []
    for x, y, s in placed:
        if (x < PAGE_MARGIN_MM or x > w - PAGE_MARGIN_MM
                or y < PAGE_MARGIN_MM or y > h - PAGE_MARGIN_MM):
            over.append(s.get("ref", "?"))
    if over:
        raise RuntimeError(
            f"以下符号将超出页面: {over}。请减小列数/间距或调整 x0/y0。"
            f"当前图纸 {w:.0f}x{h:.0f}mm, 可绘图 X {PAGE_MARGIN_MM:.0f}-{w-PAGE_MARGIN_MM:.0f}, "
            f"Y {PAGE_MARGIN_MM:.0f}-{h-PAGE_MARGIN_MM:.0f}"
        )

    # 批量创建
    batch = []
    for x, y, s in placed:
        sym = schematic_types_pb2.Symbol()
        sym.lib_id.library_nickname = s.get("lib", "Device")
        sym.lib_id.entry_name = s.get("entry", "R")
        sym.position.x_nm = round(x * MM)
        sym.position.y_nm = round(y * MM)
        if s.get("ref"):
            f = sym.fields.add(); f.name = "Reference"; f.value = s["ref"]
        if s.get("value"):
            f = sym.fields.add(); f.name = "Value"; f.value = s["value"]
        batch.append(sym)

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, batch)
    _check_create_resp(resp)

    lines = [
        f"已网格排布 {len(placed)} 个符号 "
        f"({columns} 列, 实际间距 {eff_col_gap:.1f}x{eff_row_gap:.1f}mm, "
        f"起点 {x0_mm},{y0_mm}):"
    ]
    for i, (x, y, s) in enumerate(placed):
        lines.append(
            f"  {s.get('ref', '?'):6s} {s.get('lib', 'Device')}:{s.get('entry', '?')} "
            f"@({x:.1f},{y:.1f})mm"
        )
    return "\n".join(lines)


def kicad_sch_set_sheet_info(
    title: str = "",
    date: str = "",
    revision: str = "",
    company: str = "",
    comment1: str = "",
    comment2: str = "",
    comment3: str = "",
    comment4: str = "",
    sheet_number: Optional[str] = None,
    sheet_count: Optional[str] = None,
) -> str:
    """自动填充原理图图纸信息（右下角标题栏）。

    KiCad 每张图纸右下角都有标题栏（Title/Date/Rev/Company/Comment 等），
    AI 画完图应调用本工具把信息填齐，让图纸规范、专业。

    Args:
        title: 图纸标题（如 "Keyboard-89 Matrix"、"3.3V Power"）。
        date: 日期（如 "2026-08-28"）。留空默认用当天日期。
        revision: 版本（如 "1.0"）。
        company: 公司/作者。
        comment1..4: 备注行（如板卡型号、设计师等）。
        sheet_number: 页码（如 "1"）；留空保留现有。
        sheet_count: 总页数（如 "4"）；留空保留现有。

    Returns:
        写入的图纸信息摘要。
    """
    url, header = _sch_context()
    info = base_types_pb2.TitleBlockInfo()
    info.title = title
    if date:
        info.date = date
    else:
        from datetime import date as _date
        info.date = _date.today().isoformat()
    info.revision = revision
    info.company = company
    info.comment1 = comment1
    info.comment2 = comment2
    info.comment3 = comment3
    info.comment4 = comment4

    with KiCadClient(url, client_name="kicad-mcp") as kc:
        kc.set_title_block(header.document, info)

    lines = [
        f"✅ 已填充图纸信息: 标题='{title}' 日期='{info.date}' "
        f"版本='{revision}' 公司='{company}'"
    ]
    for i, c in enumerate((comment1, comment2, comment3, comment4), 1):
        if c:
            lines.append(f"   注释{i}: {c}")
    if sheet_number or sheet_count:
        lines.append(f"   (页码/总数需在图纸设置中维护: {sheet_number}/{sheet_count})")
    return "\n".join(lines)


ALL_TOOLS = [
    kicad_sch_add_text,
    kicad_sch_add_line,
    kicad_sch_add_symbol,
    kicad_sch_add_label,
    kicad_sch_recommend_label,
    kicad_sch_transform_item,
    kicad_sch_get_items,
    kicad_sch_update_text,
    kicad_sch_delete_item,
    kicad_sch_get_symbol_pins,
    kicad_sch_connect,
    kicad_sch_erc,
    kicad_sch_detect_simulation,
    kicad_sch_simulate,
    kicad_sch_simulate_gui,
    kicad_sch_add_shape,
    kicad_sch_add_no_connect,
    kicad_sch_add_image,
    kicad_sch_get_sheet_info,
    kicad_sch_check_layout,
    kicad_sch_place_symbols_grid,
    kicad_sch_set_sheet_info,
]
