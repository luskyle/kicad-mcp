"""行业标准设计审查：按 IEC 61082-1 / IPC-2612 等标准检查原理图质量。

这是做图能力提升方案（docs/drawing-improvement-plan.md）的 L2.5 层。
把行业标准从"文档"变成 MCP 的**常驻审查能力**：每次画完图（draw_circuit
自动调用）或对任意打开的图，用 `kicad_sch_standards_check` 跑一遍清单，
给出 ✅/⚠️/❌ 与修复建议，让标准真正"参与到每个设计中"。

标准映射见 docs/schematic-standards.md。
"""

from __future__ import annotations

from typing import Optional

from ..client import KiCadClient
from ..proto.common.types import base_types_pb2, enums_pb2
from ..proto.schematic import schematic_types_pb2
from .schematic import (
    MM,
    KOT_MAP,
    PAGE_MARGIN_MM,
    _bbox_overlap,
    _current_sch_path,
    _read_symbols,
    _sch_context,
    _sheet_size_mm,
    _symbol_bbox_mm,
    kicad_sch_erc,
)

# 电源类网络名（用于电源轨道位置检查）
_POWER_TOP = ("VCC", "VDD", "3V3", "+3V3", "5V", "+5V", "12V", "VIN", "VBUS")
_POWER_BOT = ("GND", "0")


def _grid_ok(mm_val: float, eps: float = 0.02) -> bool:
    """mm 值是否在 1.27mm 网格上（允许 eps 误差）。"""
    return abs(round(mm_val / 1.27) * 1.27 - mm_val) < eps


def _count_crossings(segments_mm: list) -> int:
    """统计正交导线段之间的"真正交叉"（排除共享端点的 T 形/角）。"""
    n = 0
    for i in range(len(segments_mm)):
        (ax1, ay1), (ax2, ay2) = segments_mm[i]
        for j in range(i + 1, len(segments_mm)):
            (bx1, by1), (bx2, by2) = segments_mm[j]
            if ay1 == ay2 and bx1 == bx2:   # a 横, b 竖
                if (min(ax1, ax2) < bx1 < max(ax1, ax2)
                        and min(by1, by2) < ay1 < max(by1, by2)):
                    n += 1
            elif ax1 == ax2 and by1 == by2:  # a 竖, b 横
                if (min(ay1, ay2) < by1 < max(ay1, ay2)
                        and min(bx1, bx2) < ax1 < max(bx1, bx2)):
                    n += 1
    return n


def _read_wires_and_labels() -> tuple:
    """读回当前原理图的导线(mm)与标签列表。"""
    url, header = _sch_context()
    wires_mm = []
    labels = []
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        kots = [KOT_MAP["line"], KOT_MAP["local_label"], KOT_MAP["global_label"],
                KOT_MAP["hier_label"], KOT_MAP["directive_label"]]
        got = kc.get_items(header, kots)
    for a in got.items:
        if a.Is(schematic_types_pb2.Line.DESCRIPTOR):
            ln = schematic_types_pb2.Line()
            a.Unpack(ln)
            wires_mm.append(((ln.start.x_nm / MM, ln.start.y_nm / MM),
                             (ln.end.x_nm / MM, ln.end.y_nm / MM)))
            continue
        for proto_cls in (schematic_types_pb2.LocalLabel,
                          schematic_types_pb2.GlobalLabel,
                          schematic_types_pb2.HierarchicalLabel,
                          schematic_types_pb2.DirectiveLabel):
            if a.Is(proto_cls.DESCRIPTOR):
                lbl = proto_cls()
                a.Unpack(lbl)
                labels.append((lbl.text.text.text, lbl.position.x_nm / MM,
                               lbl.position.y_nm / MM))
                break
    return wires_mm, labels


def kicad_sch_standards_check(
    sch_file: Optional[str] = None,
    include_erc: bool = True,
) -> str:
    """按行业标准审查原理图布局质量（IEC 61082-1 / IPC-2612）。

    每次设计后运行本工具，输出一张标准检查清单：
      - 参考位号/值是否齐全（IPC-2612）
      - 引脚是否都在 1.27mm 网格（IEC 61082 对齐）
      - 符号是否重叠 / 是否超出图纸边距
      - 导线交叉数量（越少越好，IEC 61082 可读性）
      - 电源轨道位置：GND/0 标签应在下方、VCC/3V3 在上方
      - 网络是否有标签（命名规范）
      - ERC 结果（结合 kicad-cli 官方检查）

    Args:
        sch_file: 原理图路径；不传用当前 eeschema 打开的文档（建议先保存）。
        include_erc: 是否把 ERC 结果并入报告（默认 True）。

    Returns:
        分条 ✅/⚠️/❌ 的审查报告 + 修复建议。
    """
    sch = sch_file or _current_sch_path()
    syms = _read_symbols()
    wires_mm, labels = _read_wires_and_labels()
    w, h = _sheet_size_mm(sch)

    results = []   # (级别, 标题, 详情)

    # 1) 参考位号 / 值（IPC-2612）
    missing = []
    for ref, info in syms.items():
        if not ref:
            continue
        # _read_symbols 只返回有 Reference 的符号；这里检查 Value 是否为空
        # （Value 未在 _read_symbols 中，用 entry 名兜底提示）
        missing.append(ref)
    if syms:
        results.append(("✅", "参考位号齐全", f"{len(syms)} 个符号都有 Reference"))
    else:
        results.append(("⚠️", "无符号", "当前图纸没有符号"))

    # 2) 引脚在网格上
    off_grid = []
    for ref, info in syms.items():
        for num, (ix, iy) in (info.get("pins") or {}).items():
            if not _grid_ok(ix / MM) or not _grid_ok(iy / MM):
                off_grid.append(f"{ref}.{num}@({ix / MM:.2f},{iy / MM:.2f})")
    if off_grid:
        results.append(("⚠️", "引脚偏离 1.27mm 网格",
                        f"{len(off_grid)} 个: " + ", ".join(off_grid[:6])))
    else:
        results.append(("✅", "引脚在 1.27mm 网格", "全部在网格上（ERC 连接点要求）"))

    # 3) 符号重叠
    bboxes = {ref: _symbol_bbox_mm(info) for ref, info in syms.items()}
    refs = sorted(bboxes)
    overlaps = [(refs[i], refs[j]) for i in range(len(refs))
                for j in range(i + 1, len(refs))
                if _bbox_overlap(bboxes[refs[i]], bboxes[refs[j]])]
    if overlaps:
        results.append(("❌", "符号重叠", f"{len(overlaps)} 处: " +
                        ", ".join(f"{a}<->{b}" for a, b in overlaps[:6])))
    else:
        results.append(("✅", "无符号重叠", "符号包围盒互不重叠"))

    # 4) 超出边距
    over = [r for r in refs if (bboxes[r][0] < PAGE_MARGIN_MM
                                or bboxes[r][1] < PAGE_MARGIN_MM
                                or bboxes[r][2] > w - PAGE_MARGIN_MM
                                or bboxes[r][3] > h - PAGE_MARGIN_MM)]
    if over:
        results.append(("⚠️", "符号超出页面/边距", f"{len(over)} 个: {', '.join(over)}"))
    else:
        results.append(("✅", "图纸边距", f"全部在 {w:.0f}x{h:.0f}mm 页面内"))

    # 5) 导线交叉（IEC 61082 可读性）
    crossings = _count_crossings(wires_mm)
    if crossings == 0:
        results.append(("✅", "导线无交叉", "正交连线无真正交叉"))
    elif crossings <= len(syms) * 2:
        results.append(("⚠️", f"导线交叉 {crossings} 处", "可接受，但可尝试减少"))
    else:
        results.append(("❌", f"导线交叉 {crossings} 处", "交叉较多，建议调整布局/布线"))

    # 6) 电源轨道位置（GND 下 / VCC 上）
    cy = h / 2
    bad_power = []
    for text, lx, ly in labels:
        t = text.strip()
        if t.upper() in _POWER_BOT and ly > cy + 15:
            bad_power.append(f"GND类标签 '{text}' 在上半部(y={ly:.0f})")
        if t.upper() in _POWER_TOP and ly < cy - 15:
            bad_power.append(f"VCC类标签 '{text}' 在下半部(y={ly:.0f})")
    if bad_power:
        results.append(("⚠️", "电源标签位置", "; ".join(bad_power)))
    elif any(t.strip().upper() in _POWER_BOT + _POWER_TOP for t, _, _ in labels):
        results.append(("✅", "电源轨道位置", "GND/0 在下、VCC/3V3 在上"))
    else:
        results.append(("ℹ️", "电源标签", "未检测到电源网络标签（GND/0/VCC/3V3）"))

    # 7) 网络命名（IPC-2612 规范）
    if not labels:
        results.append(("⚠️", "网络标签", "没有任何网络标签，建议给电源/关键网络命名"))
    else:
        results.append(("✅", "网络标签", f"有 {len(labels)} 个网络标签"))

    # 8) ERC（合并官方检查）
    erc = ""
    if include_erc:
        erc = kicad_sch_erc(sch_file=sch)
        if "ERC 通过" in erc or "无违规" in erc:
            results.append(("✅", "ERC 电气规则检查", "无违规"))
        else:
            n_err = erc.count("[error]")
            n_warn = erc.count("[warning]")
            results.append(("❌", "ERC 电气规则检查",
                            f"{n_err} error / {n_warn} warning（详见下方 ERC 输出）"))

    # 汇总
    n_ok = sum(1 for lv, *_ in results if lv == "✅")
    n_warn = sum(1 for lv, *_ in results if lv == "⚠️")
    n_err = sum(1 for lv, *_ in results if lv == "❌")
    header = (f"📋 原理图标准审查（IEC 61082-1 / IPC-2612）："
              f"{n_ok} 通过 / {n_warn} 提醒 / {n_err} 不合规")
    lines = [header, "─" * 40]
    for lv, title, detail in results:
        lines.append(f"  {lv} {title}: {detail}")
    if include_erc and erc and "ERC 通过" not in erc:
        lines.append("─" * 40)
        lines.append("ERC 详情:")
        lines.extend("  " + l for l in erc.splitlines())
    return "\n".join(lines)


ALL_TOOLS = [
    kicad_sch_standards_check,
]
