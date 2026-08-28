"""元素重叠 / 越界检查与自动重摆（L4 增强，2026-08-28）。

用户痛点："标签文字跑出图纸"、"放置后元素重叠"。本模块把"画完检查重叠/越界、
重叠就重摆"做成 MCP 工具，参与每个设计：

  - kicad_sch_check_overlaps : 只检查，报告所有重叠（符号-符号 / 符号-标签 /
    标签-标签）与越界（超出图纸边距）元素，不动图。
  - kicad_sch_fix_overlaps   : 检查 + 自动重摆：
      * 越界标签 → 沿其连接 stub/线向页内收（保持连通，文字不出去）
      * 重叠标签 → 沿连接线/垂直方向找空位网格点（尽量保持连通）
      * 越界/重叠符号 → 若未连线则移到页内空位；已连线则报告并给出建议
    （移动符号会断线，所以已连线符号不自动移，避免静默破坏电气连接）

布局约束：所有元素锚点/文字框落在 1.27mm 网格；内容边距默认 5mm。
"""

from __future__ import annotations

import re
from typing import Optional

from ..client import KiCadClient
from ..proto.common.types import base_types_pb2, enums_pb2
from ..proto.schematic import schematic_types_pb2
from .common import kicad_save_document
from .schematic import (
    MM,
    KOT_MAP,
    _bbox_overlap,
    _current_sch_path,
    _read_symbols,
    _sch_context,
    _sheet_size_mm,
    _snap_grid,
    _symbol_bbox_mm,
)

GRID = 1.27
DEFAULT_MARGIN = 5.0
# 标签文字宽度系数（字高 * 字符数 * 系数）
_TEXT_W_FACTOR = 0.62


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def _text_width_mm(text: str, size_mm: float) -> float:
    return max(size_mm, len(text) * size_mm * _TEXT_W_FACTOR)


def _label_box_mm(text: str, x_mm: float, y_mm: float,
                  size_mm: float) -> tuple:
    """标签占用框，用 KiCad 真实文字几何：

    - 文字中心 = 锚点 + 1.43mm（L_BIDI 的 GetSchematicTextOffset）
    - 文字半宽 ≈ len*size*0.55；文字右缘 = 锚点 + 1.43 + 半宽
    - 图形框从锚点向左延伸（宽约 1.5mm 的 margin/箭头）

    之前用 len*size*0.62 估算文字宽会**低估**（漏报左侧标签文字贴符号），
    这里用真实几何，能抓到“文字右缘碰键本体”这类真实重叠。
    """
    offset = 1.43
    half = max(size_mm / 2, len(text) * size_mm * 0.55)
    return (x_mm - 1.5, y_mm - size_mm / 2,
            x_mm + offset + half, y_mm + size_mm / 2)


def _read_elements() -> tuple:
    """读回符号 / 标签 / 导线。

    Returns:
        (syms, labels, wires_mm)
        syms  : [{id, ref, lib, entry, x, y, bbox}]
        labels: [{id, type, text, x, y, size, box}]
        wires_mm: [((x1,y1),(x2,y2)), ...]（wire 层，mm）
    """
    url, header = _sch_context()
    kots = [KOT_MAP["symbol"], KOT_MAP["line"],
            KOT_MAP["local_label"], KOT_MAP["global_label"],
            KOT_MAP["hier_label"], KOT_MAP["directive_label"]]
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        got = kc.get_items(header, kots)

    syms, labels, wires_mm = [], [], []
    for a in got.items:
        if a.Is(schematic_types_pb2.Symbol.DESCRIPTOR):
            s = schematic_types_pb2.Symbol()
            a.Unpack(s)
            fields = {f.name: f.value for f in s.fields}
            ref = fields.get("Reference", "")
            if not ref:
                continue
            x, y = s.position.x_nm / MM, s.position.y_nm / MM
            pins = {p.number: (p.position.x_nm, p.position.y_nm) for p in s.pins}
            # 用"本体"包围盒（引脚范围 + 0.5mm 小余量），不用 3.81mm padding
            # —— padding 会让相邻键（20.32 间距）的 bbox 相切误判重叠。
            if pins:
                xs = [p[0] / MM for p in pins.values()]
                ys = [p[1] / MM for p in pins.values()]
                bbox = (min(xs) - 0.5, min(ys) - 0.5,
                        max(xs) + 0.5, max(ys) + 0.5)
            else:
                bbox = (x - 2.54, y - 2.54, x + 2.54, y + 2.54)
            syms.append({"id": s.id.value, "ref": ref,
                         "lib": s.lib_id.library_nickname,
                         "entry": s.lib_id.entry_name,
                         "x": x, "y": y, "bbox": bbox})
        elif a.Is(schematic_types_pb2.Line.DESCRIPTOR):
            ln = schematic_types_pb2.Line()
            a.Unpack(ln)
            if ln.layer == schematic_types_pb2.SL_WIRE:
                wires_mm.append(((ln.start.x_nm / MM, ln.start.y_nm / MM),
                                 (ln.end.x_nm / MM, ln.end.y_nm / MM),
                                 ln.id.value))
        else:
            for proto_cls, kind in [
                (schematic_types_pb2.LocalLabel, "local"),
                (schematic_types_pb2.GlobalLabel, "global"),
                (schematic_types_pb2.HierarchicalLabel, "hier"),
                (schematic_types_pb2.DirectiveLabel, "directive"),
            ]:
                if a.Is(proto_cls.DESCRIPTOR):
                    l = proto_cls()
                    a.Unpack(l)
                    text = l.text.text.text
                    x, y = l.position.x_nm / MM, l.position.y_nm / MM
                    size = (l.text.text.attributes.size.x_nm / MM
                            if l.text.text.attributes.HasField("size") else 1.27)
                    labels.append({"id": l.id.value, "type": kind, "text": text,
                                   "x": x, "y": y, "size": size,
                                   "box": _label_box_mm(text, x, y, size)})
                    break
    return syms, labels, wires_mm


def _wire_touches(wire, x_mm, y_mm, tol_mm: float = 0.15) -> bool:
    (ax, ay), (bx, by) = wire[:2]
    if abs(ax - bx) < 1e-6:   # 竖直
        return (abs(ax - x_mm) < tol_mm
                and min(ay, by) - tol_mm <= y_mm <= max(ay, by) + tol_mm)
    if abs(ay - by) < 1e-6:   # 水平
        return (abs(ay - y_mm) < tol_mm
                and min(ax, bx) - tol_mm <= x_mm <= max(ax, bx) + tol_mm)
    return False


def _label_wire(label, wires_mm):
    """返回标签锚点所在的导线线段 (a, b, id)，没有返回 None。"""
    for w in wires_mm:
        if _wire_touches(w, label["x"], label["y"]):
            return w
    return None


# ---------------------------------------------------------------------------
# 检查
# ---------------------------------------------------------------------------

def _check(syms, labels, wires_mm, page_w, page_h, margin) -> dict:
    """返回 {sym_sym:[(a,b)], sym_lab:[...], lab_lab:[...], out:[(kind,desc)]}。"""
    res = {"sym_sym": [], "sym_lab": [], "lab_lab": [], "out": []}
    # 符号-符号
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            if _bbox_overlap(syms[i]["bbox"], syms[j]["bbox"]):
                res["sym_sym"].append((syms[i]["ref"], syms[j]["ref"]))
    # 符号-标签
    for s in syms:
        for l in labels:
            if _bbox_overlap(s["bbox"], l["box"]):
                res["sym_lab"].append((s["ref"], l["text"]))
    # 标签-标签
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            if _bbox_overlap(labels[i]["box"], labels[j]["box"]):
                res["lab_lab"].append((labels[i]["text"], labels[j]["text"]))
    # 越界
    for s in syms:
        x0, y0, x1, y1 = s["bbox"]
        if x0 < margin or y0 < margin or x1 > page_w - margin or y1 > page_h - margin:
            res["out"].append(("symbol", f"{s['ref']} bbox=({x0:.1f},{y0:.1f},{x1:.1f},{y1:.1f})"))
    for l in labels:
        x0, y0, x1, y1 = l["box"]
        if x0 < margin or y0 < margin or x1 > page_w - margin or y1 > page_h - margin:
            res["out"].append(("label", f"{l['text']} @({l['x']:.1f},{l['y']:.1f}) 文字框右/下到 ({x1:.1f},{y1:.1f})"))
    return res


def _fmt_report(res: dict) -> list:
    lines = []
    n = len(res["sym_sym"]) + len(res["sym_lab"]) + len(res["lab_lab"]) + len(res["out"])
    lines.append(f"共 {n} 处问题")
    if res["sym_sym"]:
        lines.append("  · 符号重叠: " + ", ".join(f"{a}<->{b}" for a, b in res["sym_sym"][:8]))
    if res["sym_lab"]:
        lines.append("  · 标签压符号: " + ", ".join(f"{b}@{a}" for a, b in res["sym_lab"][:8]))
    if res["lab_lab"]:
        lines.append("  · 标签互叠: " + ", ".join(f"{a}+{b}" for a, b in res["lab_lab"][:8]))
    if res["out"]:
        lines.append("  · 越界:")
        for kind, desc in res["out"][:10]:
            lines.append(f"      [{kind}] {desc}")
    return lines


def kicad_sch_check_overlaps(
    page_margin_mm: float = DEFAULT_MARGIN,
    sch_file: Optional[str] = None,
) -> str:
    """检查当前原理图元素的重叠与越界（符号/标签/文字框）。

    Args:
        page_margin_mm: 内容边距（元素不能超出 图纸-边距，默认 5mm）。
        sch_file: 原理图路径；不传用当前 eeschema 打开的文档。

    Returns:
        逐条列出重叠（符号-符号 / 符号-标签 / 标签-标签）与越界元素；
        无问题返回通过。只检查不修改。
    """
    w, h = _sheet_size_mm(sch_file)
    syms, labels, wires = _read_elements()
    res = _check(syms, labels, wires, w, h, page_margin_mm)
    n = len(res["sym_sym"]) + len(res["sym_lab"]) + len(res["lab_lab"]) + len(res["out"])
    head = ("✅ 无重叠/越界" if n == 0
            else f"❌ 发现 {n} 处重叠/越界")
    lines = [f"🔎 重叠/越界检查（{w:.0f}x{h:.0f}mm，边距 {page_margin_mm}mm）：{head}"]
    lines += _fmt_report(res)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 自动重摆
# ---------------------------------------------------------------------------

def _move_label(label, x_mm: float, y_mm: float) -> None:
    url, header = _sch_context()
    proto_cls = {
        "local": schematic_types_pb2.LocalLabel,
        "global": schematic_types_pb2.GlobalLabel,
        "hier": schematic_types_pb2.HierarchicalLabel,
        "directive": schematic_types_pb2.DirectiveLabel,
    }[label["type"]]
    l = proto_cls()
    l.id.value = label["id"]
    l.position.x_nm = round(x_mm * MM)
    l.position.y_nm = round(y_mm * MM)
    l.text.text.text = label["text"]
    l.text.text.position.x_nm = round(x_mm * MM)
    l.text.text.position.y_nm = round(y_mm * MM)
    l.text.text.attributes.size.x_nm = round(label["size"] * MM)
    l.text.text.attributes.size.y_nm = round(label["size"] * MM)
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.update_items(header, [l])
    for r in resp.updated_items:
        if r.status.code != 1:
            raise RuntimeError(f"更新标签失败: {r.status.error_message}")


def _move_symbol(sym, x_mm: float, y_mm: float) -> None:
    url, header = _sch_context()
    s = schematic_types_pb2.Symbol()
    s.id.value = sym["id"]
    s.position.x_nm = round(x_mm * MM)
    s.position.y_nm = round(y_mm * MM)
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.update_items(header, [s])
    for r in resp.updated_items:
        if r.status.code != 1:
            raise RuntimeError(f"更新符号失败: {r.status.error_message}")


def _extend_wire(wire, label, nx_mm: float, ny_mm: float) -> None:
    """把标签连接的导线从旧锚点延伸到新锚点（删旧线 + 画新线）。

    用于"有线标签越界但沿线收不进"的场景：标签移到页内空位后，
    导线另一端（引脚/trunk 侧）不变，标签端改到新位置，保持连通。
    """
    (ax, ay), (bx, by), wid = wire[:3]
    # 标签端 = 离标签旧锚点近的那端
    if abs(ax - label["x"]) + abs(ay - label["y"]) <= \
            abs(bx - label["x"]) + abs(by - label["y"]):
        ox, oy = bx, by
    else:
        ox, oy = ax, ay
    # 删旧线
    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        kc.delete_items(header, [wid])
    # 画新线：另一端 -> 新标签锚点（吸附网格）
    from .schematic import kicad_sch_add_line
    kicad_sch_add_line(ox, oy, nx_mm, ny_mm)


def _occupied_boxes(syms, labels) -> list:
    return [s["bbox"] for s in syms] + [l["box"] for l in labels]


def _point_free(x_mm, y_mm, box_w, box_h, occupied, page_w, page_h, margin) -> bool:
    """候选锚点 (x,y) 处放一个 box_w*box_h 的框是否不与已占用重叠且不越界。"""
    if x_mm - margin < 0 or y_mm - margin < 0:
        return False
    if x_mm + box_w > page_w - margin or y_mm + box_h > page_h - margin:
        return False
    cand = (x_mm, y_mm, x_mm + box_w, y_mm + box_h)
    return not any(_bbox_overlap(cand, o) for o in occupied)


def _relocate_label(l, wires, syms, labels, w, h, margin,
                   allow_detach: bool = False) -> Optional[tuple]:
    """为越界/重叠的标签找新锚点（1.27mm 网格）。

    有线标签只沿连接导线移动（保持连通）；无线标签或 allow_detach 时，
    可自由在垂直/水平方向找页内空位。

    Returns:
        (new_x, new_y, on_wire) 或 None（无解）。on_wire=True 表示新位置
        仍在原导线上（无需动线）；False 表示自由位置（有线标签需延伸 stub）。
    """
    bw = _text_width_mm(l["text"], l["size"])
    bh = l["size"]

    def _box_ok(cx, cy) -> bool:
        cb = (cx - 0.5, cy - bh / 2, cx + bw, cy + bh / 2)
        if (cb[0] < margin or cb[1] < margin
                or cb[2] > w - margin or cb[3] > h - margin):
            return False
        for o in _occupied_boxes(syms, labels):
            if _bbox_overlap(cb, o):
                return False
        return True

    def _first(cands):
        seen = set()
        for cx, cy in cands:
            key = (round(cx, 2), round(cy, 2))
            if key in seen:
                continue
            seen.add(key)
            if abs(cx - l["x"]) < 0.01 and abs(cy - l["y"]) < 0.01:
                continue
            if _box_ok(cx, cy):
                return cx, cy
        return None

    wire = _label_wire(l, wires)
    if wire is not None:
        # 沿线候选（保持连通，文字收进页内 / 避开重叠）
        (ax, ay), (bx, by) = wire[:2]
        L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        on_cands = []
        if L > 1e-6:
            ux, uy = (bx - ax) / L, (by - ay) / L
            for sign in (1, -1):
                for k in range(1, 60):
                    cx = _snap_grid(l["x"] + sign * ux * k * GRID)
                    cy = _snap_grid(l["y"] + sign * uy * k * GRID)
                    if not _wire_touches(wire, cx, cy):
                        break
                    on_cands.append((cx, cy))
        hit = _first(on_cands)
        if hit is not None:
            return hit[0], hit[1], True
        if not allow_detach:
            return None
    # 自由候选（垂直 / 水平；无线标签，或有线标签允许延伸时兜底）
    free = []
    for k in range(1, 60):
        free.append((l["x"], _snap_grid(l["y"] + k * GRID)))
        free.append((l["x"], _snap_grid(l["y"] - k * GRID)))
        free.append((_snap_grid(l["x"] + k * GRID), l["y"]))
        free.append((_snap_grid(l["x"] - k * GRID), l["y"]))
    hit = _first(free)
    if hit is not None:
        return hit[0], hit[1], False
    return None


def kicad_sch_fix_overlaps(
    page_margin_mm: float = DEFAULT_MARGIN,
    max_iterations: int = 10,
    move_connected_symbols: bool = False,
    move_label_on_symbol: bool = False,
    sch_file: Optional[str] = None,
) -> str:
    """检查重叠/越界并自动重摆（标签优先，符号视是否接线）。

    Args:
        page_margin_mm: 内容边距（默认 5mm）。
        max_iterations: 最大重摆轮数（每轮把所有问题修一遍，默认 10）。
        move_connected_symbols: 是否也移动已接线的符号（默认 False ——
            移动符号会断线，默认只报告；True 时会移动并提示需重新布线）。
        move_label_on_symbol: 是否也重摆"压到符号但已接线"的标签（默认 False ——
            这类常是引脚读回 bug / 大符号贴边，移动会延伸 stub 且易振荡，默认
            只报告；True 时尽量移开并延伸 stub 保持连通）。
        sch_file: 原理图路径；不传用当前 eeschema 打开的文档。

    Returns:
        每轮修复记录 + 剩余问题。重摆后保存文档。
    """
    w, h = _sheet_size_mm(sch_file)
    lines = [f"🔧 重叠/越界自动重摆（图纸 {w:.0f}x{h:.0f}mm，边距 {page_margin_mm}mm）"]
    total_fixed = 0

    last = None
    for it in range(1, max_iterations + 1):
        syms, labels, wires = _read_elements()
        res = _check(syms, labels, wires, w, h, page_margin_mm)
        n_problem = (len(res["sym_sym"]) + len(res["sym_lab"])
                     + len(res["lab_lab"]) + len(res["out"]))
        if n_problem == 0:
            lines.append(f"第{it}轮后：全部干净 ✅")
            break
        # 振荡防护：问题数未减少说明在来回让位，停止，避免把图改乱
        if last is not None and n_problem >= last:
            lines.append(f"第{it}轮：问题数未减少（{last}→{n_problem}），停止自动重摆避免振荡。")
            break
        last = n_problem

        fixed = 0
        # 1) 标签问题分类处理：
        #    - 有线标签压符号（且未越界、未互叠）→ 不自动移（常是引脚读回 bug /
        #      大符号贴边，移动会延伸 stub 且无解→振荡），仅报告
        #    - 越界 / 无线标签 / 标签互叠 → 自动重摆（优先沿线保持连通）
        for l in labels:
            box = l["box"]
            in_page = (box[0] >= page_margin_mm and box[1] >= page_margin_mm
                       and box[2] <= w - page_margin_mm and box[3] <= h - page_margin_mm)
            sym_hit = any(_bbox_overlap(box, s["bbox"]) for s in syms)
            lab_hit = any(_bbox_overlap(box, o["box"]) for o in labels if o is not l)
            if in_page and not sym_hit and not lab_hit:
                continue
            wire = _label_wire(l, wires)
            wired = wire is not None
            if wired and in_page and sym_hit and not lab_hit:
                if not move_label_on_symbol:
                    lines.append(f"  ⚠️ 标签 {l['text']} @({l['x']:.1f},{l['y']:.1f}) 压到符号但已接线，"
                                 f"不自动移动（避免破坏连接/振荡）。建议用 kicad_sch_draw_circuit 重排，"
                                 f"或 fix_overlaps(move_label_on_symbol=True) 强制移开。")
                    continue
                # 强制：移开并延伸 stub（保持连通）
                new_pos = _relocate_label(l, wires, syms, labels, w, h, page_margin_mm,
                                          allow_detach=True)
                if new_pos is None:
                    lines.append(f"  ⚠️ 标签 {l['text']} @({l['x']:.1f},{l['y']:.1f}) 压符号且找不到空位，请人工调整。")
                    continue
                nx, ny, _onw = new_pos
                if abs(nx - l["x"]) < 0.01 and abs(ny - l["y"]) < 0.01:
                    continue
                _extend_wire(wire, l, nx, ny)
                _move_label(l, nx, ny)
                fixed += 1
                total_fixed += 1
                lines.append(f"  移标签 {l['text']}: ({l['x']:.1f},{l['y']:.1f})→({nx:.1f},{ny:.1f})（移开符号，延伸 stub 保持连通）")
                continue
            # 越界 / 无线 / 互叠 → 尝试重摆（有线优先沿线）
            new_pos = _relocate_label(l, wires, syms, labels, w, h, page_margin_mm,
                                      allow_detach=not wired)
            if new_pos is None and wired:
                new_pos = _relocate_label(l, wires, syms, labels, w, h, page_margin_mm,
                                          allow_detach=True)
            if new_pos is None:
                hint = "（有线标签只沿线移动，需保持连通）" if wired else ""
                lines.append(f"  ⚠️ 标签 {l['text']} @({l['x']:.1f},{l['y']:.1f}) "
                             f"越界/重叠但找不到空位{hint}，请人工调整。")
                continue
            nx, ny, on_wire = new_pos
            if abs(nx - l["x"]) < 0.01 and abs(ny - l["y"]) < 0.01:
                continue
            reason = "收进页内" if not in_page else "避开重叠"
            note = ""
            if wired and not on_wire:
                _extend_wire(wire, l, nx, ny)
                note = "（延伸 stub 保持连通）"
            _move_label(l, nx, ny)
            fixed += 1
            total_fixed += 1
            lines.append(f"  移标签 {l['text']}: ({l['x']:.1f},{l['y']:.1f})→({nx:.1f},{ny:.1f})（{reason}{note}）")

        # 3) 越界 / 重叠的未连线符号 → 移到页内空位
        syms, labels, wires = _read_elements()
        res3 = _check(syms, labels, wires, w, h, page_margin_mm)
        sym_names_overlap = {r for pair in res3["sym_sym"] for r in pair}
        sym_names_out = {s["ref"] for s in syms
                         if s["bbox"][0] < page_margin_mm or s["bbox"][1] < page_margin_mm
                         or s["bbox"][2] > w - page_margin_mm or s["bbox"][3] > h - page_margin_mm}
        for s in syms:
            if s["ref"] not in sym_names_overlap and s["ref"] not in sym_names_out:
                continue
            wired = any(_wire_touches(wt, px / MM, py / MM)
                        for wt in wires
                        for px, py in _read_symbols().get(s["ref"], {}).get("pins", {}).values())
            if wired and not move_connected_symbols:
                lines.append(f"  ⚠️ 符号 {s['ref']} 重叠/越界但已接线，不自动移动（避免断线）。"
                             f"建议用 kicad_sch_draw_circuit 重排或人工调整。")
                continue
            # 找空位：页内网格扫描
            placed = False
            for yy in [s["y"]] + [s["y"] + k * 2 * GRID for k in (1, -1, 2, -2, 3, -3, 4, -4)]:
                for xx in [s["x"]] + [s["x"] + k * 2 * GRID for k in (1, -1, 2, -2, 3, -3, 4, -4)]:
                    xx, yy = _snap_grid(xx), _snap_grid(yy)
                    bw = s["bbox"][2] - s["bbox"][0]
                    bh = s["bbox"][3] - s["bbox"][1]
                    if _point_free(xx, yy, bw, bh, _occupied_boxes(syms, labels), w, h, page_margin_mm):
                        _move_symbol(s, xx, yy)
                        fixed += 1
                        total_fixed += 1
                        lines.append(f"  移符号 {s['ref']}: ({s['x']:.1f},{s['y']:.1f})→({xx:.1f},{yy:.1f})")
                        placed = True
                        break
                if placed:
                    break
            if not placed:
                lines.append(f"  ⚠️ 符号 {s['ref']} 找不到空位，请人工调整。")

        if fixed == 0:
            lines.append(f"第{it}轮：无可自动修复项（剩余需人工）")
            break
        kicad_save_document()

    # 最终报告
    syms, labels, wires = _read_elements()
    res = _check(syms, labels, wires, w, h, page_margin_mm)
    n = (len(res["sym_sym"]) + len(res["sym_lab"]) + len(res["lab_lab"]) + len(res["out"]))
    lines.append(f"— 重摆完成：共移动 {total_fixed} 处，剩余问题 {n} —")
    lines += _fmt_report(res)
    return "\n".join(lines)


ALL_TOOLS = [
    kicad_sch_check_overlaps,
    kicad_sch_fix_overlaps,
]
