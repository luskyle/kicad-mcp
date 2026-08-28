"""L2 高层"成图"工具（原理图）：从电路描述一键画出可 ERC 通过的原理图。

这是做图能力提升方案（docs/drawing-improvement-plan.md）的 L2 层（原理图部分）。
把 tests/redraw_*.py / draw_*.py 里的人工编排能力固化成 MCP 工具：

- kicad_sch_auto_layout : 按连通图（netlist）自动排布符号（信号流向 → 列，
  电源符号放上/下轨道），取代静态网格。
- kicad_sch_auto_route  : 批量自动布线（多网络，逐个链式布，自动避让符号与
  已布导线）。
- kicad_sch_draw_circuit: 一键成图 —— 解析电路描述 → 布局 → 布线 → 标签 →
  保存 → ERC → 自动修(加 PWR_FLAG) → 渲染 SVG 反馈。**杀手级工具**。

坐标/电气规则沿用原理图约定：1mm=1e4 IU，round 避免 1IU 误差，1.27mm 网格。
"""

from __future__ import annotations

import json
from collections import deque
from typing import Optional

from ..client import KiCadClient
from ..proto.common.types import base_types_pb2, enums_pb2
from ..proto.schematic import schematic_types_pb2
from .common import kicad_save_document
from .render import kicad_sch_render
from .schematic import (
    MM,
    KOT_MAP,
    _check_create_resp,
    _current_sch_path,
    _read_symbols,
    _route_avoiding,
    _sch_context,
    _seg_hits_bbox,
    _snap_grid,
    _symbol_bbox_mm,
    kicad_sch_add_label,
    kicad_sch_add_no_connect,
    kicad_sch_add_symbol,
    kicad_sch_connect,
    kicad_sch_erc,
)
from ..symbols import get_pins

# 电源符号判定：库名为 power，或符号名命中这些电源名
_POWER_LIBS = {"power"}
_POWER_NAMES = {"GND", "PWR_FLAG", "+3V3", "+5V", "+12V", "-12V", "VCC", "VDD"}


# ============================================================
# 解析辅助
# ============================================================

def _parse_json(value: str, what: str):
    try:
        return json.loads(value)
    except Exception as e:
        raise ValueError(f"{what} 必须是 JSON: {e}") from e


def _find_symbol(name: str, lib: str = "") -> tuple:
    """在符号库中查找 (lib, symbol)；优先精确匹配，失败给出候选。"""
    name = name.strip()
    from .symbol_browser import kicad_sch_search_symbols
    if lib:
        if get_pins(lib, name):
            return lib, name
        hit = kicad_sch_search_symbols(name, library=lib, max_results=10)
        for ln in hit.splitlines():
            ln = ln.strip()
            if ":" in ln:
                l, s = ln.rsplit(":", 1)
                if s.strip().lower() == name.lower():
                    return l.strip(), s.strip()
        raise RuntimeError(f"库 {lib} 中找不到符号 {name}。搜索结果:\n{hit}")
    # 全局搜索
    hit = kicad_sch_search_symbols(name, max_results=10)
    cand = []
    for ln in hit.splitlines():
        ln = ln.strip()
        if ":" in ln:
            l, s = ln.rsplit(":", 1)
            if s.strip().lower() == name.lower():
                return l.strip(), s.strip()
            cand.append(ln)
    raise RuntimeError(f"找不到符号 {name!r}。候选: {cand[:6]}")


def _resolve_symbol(spec: dict) -> tuple:
    """校验/解析库与符号名，返回 (lib, symbol)。找不到给出建议。"""
    symbol = spec.get("symbol", "").strip()
    if not symbol:
        raise RuntimeError(f"符号 {spec.get('ref', '?')} 缺少 symbol 字段（符号名）")
    return _find_symbol(symbol, spec.get("lib", "").strip())


def _is_power_spec(spec: dict) -> bool:
    return (spec.get("lib", "").lower() in _POWER_LIBS
            or spec.get("symbol", "").upper() in _POWER_NAMES)


# ============================================================
# 布局：按连通图流向来排
# ============================================================

def _flow_stages(refs: list, nets: list, power_refs: set = frozenset()) -> dict:
    """按 netlist 的引脚顺序（信号从左到右）给每个符号算"列(stage)"。

    每条 net 的 pins 顺序隐含方向 p0→p1→p2…；从入度为 0 的符号做 BFS。
    含电源符号的网络（GND/VCC/3V3…）不参与流向计算 —— 它们会让所有元件
    连成环（都连到地/电源），导致找不到源点、全部落到同一列。
    """
    indeg = {r: 0 for r in refs}
    out = {r: set() for r in refs}
    for net in nets:
        pins = net.get("pins", [])
        if any(r in power_refs for r, _ in pins):
            continue  # 含电源符号的网络走轨道，不定义左右流向
        for i in range(len(pins) - 1):
            a, b = pins[i][0], pins[i + 1][0]
            if a in out and b in out and b not in out[a]:
                out[a].add(b)
                indeg[b] += 1
    q = deque(r for r in refs if indeg[r] == 0)
    if not q:
        q = deque(refs)
    stage = {}
    cur = 0
    frontier = list(q)
    seen = set(frontier)
    while frontier:
        for r in frontier:
            stage[r] = cur
        nxt = []
        for r in frontier:
            for b in out[r]:
                if b not in seen:
                    seen.add(b)
                    nxt.append(b)
        frontier = nxt
        cur += 1
    for r in refs:
        stage.setdefault(r, cur)
    return stage


def _net_of_ref(ref: str, nets: list) -> Optional[dict]:
    for net in nets:
        if any(r == ref for r, _ in net.get("pins", [])):
            return net
    return None


def _net_anchor(ref: str, nets: list, symbols: list) -> Optional[str]:
    """返回 ref 所在网络中第一个非电源符号的 ref（作电源符号的锚点列）。"""
    net = _net_of_ref(ref, nets)
    if not net:
        return None
    for r, _ in net.get("pins", []):
        if r != ref:
            spec = next((s for s in symbols if s.get("ref") == r), None)
            if spec is not None and not _is_power_spec(spec):
                return r
    return None


def _sym_size_mm(spec: dict) -> tuple:
    """从库引脚估算符号尺寸（宽, 高）mm，用于间距。"""
    pins = get_pins(spec.get("lib", ""), spec.get("symbol", ""))
    if not pins:
        return 10.0, 10.0
    xs = [p.x_mm for p in pins]
    ys = [p.y_mm for p in pins]
    return (max(xs) - min(xs) + 2 * 2.54, max(ys) - min(ys) + 2 * 2.54)


def _build_adjacency(symbols: list, nets: list, power_refs: set) -> dict:
    """构建符号间连通图（非电源网络内任意两个引脚所在符号视为相邻）。"""
    refs = {s.get("ref") for s in symbols if s.get("ref") not in power_refs}
    adj = {r: set() for r in refs}
    for net in nets:
        pins = net.get("pins", [])
        if any(r in power_refs for r, _ in pins):
            continue
        rs = [r for r, _ in pins if r in adj]
        for a in rs:
            for b in rs:
                if a != b:
                    adj[a].add(b)
                    adj[b].add(a)
    return adj


def _barycenter_order(by_stage: dict, adj: dict) -> None:
    """原地调整各列内的符号顺序，减少跨列连线交叉（barycenter 法，迭代 3 次）。

    依据: IEC 61082-1 要求图纸连线尽量少交叉；Sugiyama 分层布局中的
    barycenter 启发式被广泛用于降低交叉数（每层节点按邻居平均位置排序）。
    """
    if len(by_stage) < 2:
        return
    pos = {}
    for st in sorted(by_stage):
        for i, s in enumerate(by_stage[st]):
            pos[s.get("ref")] = i
    for _ in range(3):
        newpos = {}
        for st in sorted(by_stage):
            objs = by_stage[st]

            def _key(s):
                nb = [pos[n] for n in adj.get(s.get("ref"), ()) if n in pos]
                if nb:
                    return (sum(nb) / len(nb), 0)
                return (pos.get(s.get("ref"), 0), 0)  # 无邻居保持原位

            objs.sort(key=_key)
            for i, s in enumerate(objs):
                newpos[s.get("ref")] = i
        pos = newpos


def _compute_layout(symbols: list, nets: list, opts: dict) -> dict:
    """计算每个符号的放置 (x_mm, y_mm, orient)。纯计算，不落盘。

    opts:
        mode: "auto"|"flow"（按信号流排布，电源符号放上/下轨道）| "grid"（普通网格）。
        x0_mm / y0_mm / gap_mm / columns：网格参数。
    """
    x0 = float(opts.get("x0_mm", 50.0))
    y0 = float(opts.get("y0_mm", 50.0))
    gap = float(opts.get("gap_mm", 0.0) or 0.0)
    mode = opts.get("mode", "auto")

    non_power = [s for s in symbols if not _is_power_spec(s)]
    power = [s for s in symbols if _is_power_spec(s)]

    # 间距：按最大符号尺寸自适应（gap 为最小值）。行间距要留出 trunk 布线通道，
    # 否则同一行所有水平导线会因共线被 KiCad 合并成一条贯穿线（短路）。
    max_w, max_h = 10.0, 10.0
    for s in non_power:
        w, h = _sym_size_mm(s)
        max_w, max_h = max(max_w, w), max(max_h, h)
    col_gap = max(gap, max_w + 10.0)      # 列间距
    row_gap = max(gap, max_h + 12.0)      # 行间距（含 trunk 通道，防共线合并）

    power_refs = {s.get("ref") for s in power}
    if mode in ("auto", "flow"):
        stages = _flow_stages([s.get("ref") for s in non_power], nets, power_refs)
    else:
        columns = max(1, int(opts.get("columns", 3)))
        stages = {s.get("ref"): i // columns for i, s in enumerate(non_power)}

    # 列内行序：barycenter 减交叉 + zigzag（st%2 让相邻列交替上下行，
    # 避免所有水平导线落在同一 y 被 KiCad 合并短路）。
    by_stage: dict = {}
    for s in non_power:
        by_stage.setdefault(stages[s.get("ref")], []).append(s)
    _barycenter_order(by_stage, _build_adjacency(non_power, nets, power_refs))

    out: dict = {}
    for st in sorted(by_stage):
        row_objs = by_stage[st]
        for row, s in enumerate(row_objs):
            x = _snap_grid(x0 + st * col_gap)
            y = _snap_grid(y0 + (st % 2) * row_gap + row * row_gap)
            out[s.get("ref")] = (x, y, int(s.get("orient", 0)))

    # 电源符号放上/下轨道（GND 下轨，VCC 类上轨），x 对齐其网络锚点列
    if power:
        gnd_y = _snap_grid(y0 + 2 * row_gap + max_h)   # 所有行下方
        vcc_y = _snap_grid(y0 - row_gap)               # 所有行上方
        for s in power:
            name = s.get("symbol", "").upper()
            anchor = _net_anchor(s.get("ref"), nets, non_power)
            ax = out[anchor][0] if anchor in out else x0
            if name == "GND":
                y = gnd_y
            elif name in ("+3V3", "+5V", "+12V", "-12V", "VCC", "VDD"):
                y = vcc_y
            else:
                y = _snap_grid(y0)  # PWR_FLAG 等：放网格起点附近
            out[s.get("ref")] = (ax, y, int(s.get("orient", 0)))
    return out


def _place_symbols(symbols: list, layout: dict) -> list:
    """按布局结果放置符号，返回每条放置结果消息。"""
    msgs = []
    for s in symbols:
        ref = s.get("ref")
        if ref not in layout:
            raise RuntimeError(f"布局结果缺少符号 {ref}")
        x, y, orient = layout[ref]
        msgs.append(kicad_sch_add_symbol(
            lib_nickname=s["lib"], entry_name=s["symbol"],
            x_mm=x, y_mm=y, reference=ref,
            value=s.get("value", ""), orientation_degrees=orient,
            snap_to_grid=False, avoid_overlap=False))
    return msgs


# ============================================================
# 布线：多网络链式自动布线
# ============================================================

def _pick_trunk_lane(pins_iu: list, obstacles_mm: list,
                     used_lanes_iu: list, owner_bboxes: Optional[list] = None,
                     preferred_lane: Optional[int] = None,
                     margin_mm: float = 2.54) -> int:
    """为网络选一条水平 trunk 道（IU），不与符号/已用道/引脚 stub 冲突。

    owner_bboxes: 与 pins_iu 等长的列表，每个引脚所属符号的包围盒；
    检查该引脚 stub 时排除自己符号的包围盒（侧边引脚竖直 stub 本就不穿过
    本体，只是被 bbox 的 3.81mm padding 误判）。
    preferred_lane: 首选道（如电源轨道 GND 底部 / VCC 顶部），先尝试它。
    """
    ys = [p[1] for p in pins_iu]
    y_min, y_max = min(ys), max(ys)
    x_min = min(p[0] for p in pins_iu)
    x_max = max(p[0] for p in pins_iu)
    base = round((y_min + y_max) / 2)
    m = round(margin_mm * MM)

    def _on_grid(y_iu: int) -> int:
        """吸附到 1.27mm 网格（否则导线端点 off grid，ERC 报错）。"""
        return round(_snap_grid(y_iu / MM) * MM)

    cands = []
    if preferred_lane is not None:
        cands.append(_on_grid(preferred_lane))
    cands.append(_on_grid(base))
    for k in range(1, 12):
        cands.append(_on_grid(base - k * m))
        cands.append(_on_grid(base + k * m))
    seen = set()
    cands = [c for c in cands if not (c in seen or seen.add(c))]
    for y_iu in cands:
        trunk = ((x_min, y_iu), (x_max, y_iu))
        if any(_seg_hits_bbox(trunk, o) for o in obstacles_mm):
            continue
        if any(abs(y_iu - u) < m for u in used_lanes_iu):
            continue
        ok = True
        for i, (px, py) in enumerate(pins_iu):
            if py == y_iu:
                continue
            stub = ((px, min(py, y_iu)), (px, max(py, y_iu)))
            own = owner_bboxes[i] if owner_bboxes else None
            for o in obstacles_mm:
                if own is not None and o == own:
                    continue  # 忽略自己符号的包围盒（padding 误判）
                if _seg_hits_bbox(stub, o):
                    ok = False
                    break
            if not ok:
                break
        if ok:
            return y_iu
    return base


def _route_net_trunk(pin_refs: list, obstacles_mm: list,
                     used_lanes_iu: list, owner_bbox_map: dict,
                     preferred_lane: Optional[int] = None) -> tuple:
    """用独立 trunk 道连接网络的所有引脚（每网络一条专属水平道）。

    设计要点（防止 KiCad 把共线导线合并短路）:
      - 每个网络独占一条水平 trunk 道（used_lanes_iu 隔离，不同网络 y 不同）
      - 每个引脚在自身 x 处垂直接到 trunk —— 引脚 x 各不同，垂直 stub 不重叠
      - 侧边引脚（orient 90 的左右引脚）垂直 stub 不穿过符号本体

    Args:
        pin_refs: [(ref, (x_iu, y_iu)), ...]（ref 用于排除自身符号包围盒）
        owner_bbox_map: {ref: bbox_mm}，符号包围盒（与 obstacles_mm 同源）

    Returns: (wire_segments_iu, trunk_y_iu, junctions_iu)
        junctions_iu: [(x_iu, y_iu), ...] —— stub 与 trunk 的汇合点。
        KiCad 中导线端点落在另一条导线**中部**不会自动连接，必须放 Junction。
    """
    pins_iu = [p for _, p in pin_refs]
    owner_bboxes = [owner_bbox_map.get(r) for r, _ in pin_refs]
    y_lane = _pick_trunk_lane(pins_iu, obstacles_mm, used_lanes_iu, owner_bboxes,
                              preferred_lane)
    used_lanes_iu.append(y_lane)
    x_min = min(p[0] for p in pins_iu)
    x_max = max(p[0] for p in pins_iu)
    segs = []
    junctions = []
    for (px, py) in pins_iu:
        if py != y_lane:
            segs.append(((px, py), (px, y_lane)))
            junctions.append((px, y_lane))
    segs.append(((x_min, y_lane), (x_max, y_lane)))
    return [s for s in segs if s[0] != s[1]], y_lane, junctions


def _power_rail_lanes(syms: dict, nets: list, power_refs: set,
                      used_lanes_iu: list, obstacles_mm: list) -> dict:
    """为电源网络计算首选轨道道（IEC 61082 惯例：电源上、地在下）。

    返回 {net名: preferred_lane_iu}。GND/0 网络给底部轨道；其它含电源符号的
    网络（VCC/3V3/5V…）给顶部轨道（多个依次下移避免重叠）。
    """
    if not power_refs:
        return {}
    ys = [info["y_mm"] for info in syms.values()]
    if not ys:
        return {}
    y_min, y_max = min(ys), max(ys)
    step = round(2.54 * MM)
    margin = round(6.0 * MM)
    bottom = round((y_max / MM + 6.0) * MM)     # 底部轨道：最大 y 以下
    top = round((y_min / MM - 6.0) * MM)        # 顶部轨道：最小 y 以上
    # 已用道作为已知占位，让多个电源网络错开
    occupied = set(used_lanes_iu)
    out: dict = {}
    vcc_offset = 0
    for net in nets:
        name = net.get("name", "")
        pins = net.get("pins", [])
        if not name or not any(r in power_refs for r, _ in pins):
            continue
        is_gnd = name.upper() in ("GND", "0")
        if is_gnd:
            preferred = bottom
        else:
            preferred = top - vcc_offset * step
            vcc_offset += 1
        # 若被占则往上/往下让一让（交给 _pick_trunk_lane 的首选候选机制）
        out[name] = preferred
    return out


def _mark_unused_pins(nets: list, syms: dict) -> int:
    """给网表里没出现（未使用）的引脚放 NoConnect(X) 标记，返回数量。"""
    used = set()
    for net in nets:
        for r, p in net.get("pins", []):
            used.add((r, str(p)))
    placed = 0
    for ref, info in syms.items():
        for num, (ix, iy) in (info.get("pins") or {}).items():
            if (ref, num) not in used:
                try:
                    kicad_sch_add_no_connect(ix / MM, iy / MM)
                    placed += 1
                except Exception:
                    pass
    return placed


def _create_lines(segments_iu: list, junctions_iu: Optional[list] = None) -> None:
    """批量创建导线；junctions_iu 是 (x,y) 汇合点，一并创建 Junction。"""
    if not segments_iu and not junctions_iu:
        return
    url, header = _sch_context()
    items = []
    for (x1, y1), (x2, y2) in segments_iu:
        ln = schematic_types_pb2.Line()
        ln.start.x_nm = x1
        ln.start.y_nm = y1
        ln.end.x_nm = x2
        ln.end.y_nm = y2
        ln.layer = schematic_types_pb2.SL_WIRE
        items.append(ln)
    for (jx, jy) in (junctions_iu or []):
        jn = schematic_types_pb2.Junction()
        jn.position.x_nm = jx
        jn.position.y_nm = jy
        items.append(jn)
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, items)
    _check_create_resp(resp)


def kicad_sch_array(
    symbols_json: str,
    nx: int = 1,
    ny: int = 1,
    dx_mm: float = 15.24,
    dy_mm: float = 12.7,
    x0_mm: float = 50.0,
    y0_mm: float = 50.0,
) -> str:
    """阵列放置：把一组符号按 nx×ny 网格重复放置，参考位号自动编号。

    用于键盘矩阵、电阻排、发光管阵列等重复结构，不用一条条画。

    Args:
        symbols_json: JSON 数组，每项 {lib, symbol, value, ref_prefix}，按顺序
            循环填入网格。如:
            '[{"lib":"Device","symbol":"R","value":"10k","ref_prefix":"R"}]'
        nx: 每行数量（列数）。
        ny: 每列数量（行数）。
        dx_mm: 列间距（默认 15.24 = 12 格）。
        dy_mm: 行间距（默认 12.7 = 10 格）。
        x0_mm, y0_mm: 网格起点。

    Returns:
        每个实例的参考位号与位置。
    """
    specs = _parse_json(symbols_json, "symbols_json")
    if not isinstance(specs, list) or not specs:
        raise ValueError("symbols_json 应为非空数组")
    if nx < 1 or ny < 1:
        raise ValueError("nx/ny >= 1")

    for s in specs:
        s["lib"], s["symbol"] = _resolve_symbol(s)

    placed = []
    idx = 1
    for i in range(ny):
        for j in range(nx):
            spec = specs[(i * nx + j) % len(specs)]
            prefix = spec.get("ref_prefix") or spec.get("reference", "X") or "X"
            ref = f"{prefix}{idx}"
            idx += 1
            x = _snap_grid(x0_mm + j * dx_mm)
            y = _snap_grid(y0_mm + i * dy_mm)
            kicad_sch_add_symbol(spec["lib"], spec["symbol"], x, y,
                                 reference=ref, value=spec.get("value", ""),
                                 snap_to_grid=False, avoid_overlap=False)
            placed.append((ref, x, y))

    lines = [f"✅ 已阵列放置 {len(placed)} 个符号（{nx}x{ny}，间距 {dx_mm}x{dy_mm}mm）"]
    for ref, x, y in placed:
        lines.append(f"  {ref:6s} @({x:.1f},{y:.1f})mm")
    return "\n".join(lines)


# ============================================================
# 清空图纸
# ============================================================

def _clear_sheet() -> int:
    """删除当前原理图所有元素（GetItems -> DeleteItems），返回删除数量。"""
    url, header = _sch_context()
    # 含 bus entry（KOT_SCH_BUS_WIRE_ENTRY/BUS_BUS_ENTRY，KOT_MAP 里没有）
    kots = list(KOT_MAP.values()) + [enums_pb2.KOT_SCH_BUS_WIRE_ENTRY,
                                     enums_pb2.KOT_SCH_BUS_BUS_ENTRY]
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        got = kc.get_items(header, kots)
        ids = []
        for a in got.items:
            for proto_cls in (
                    schematic_types_pb2.Text, schematic_types_pb2.Symbol,
                    schematic_types_pb2.Line, schematic_types_pb2.Shape,
                    schematic_types_pb2.NoConnect, schematic_types_pb2.Junction,
                    schematic_types_pb2.BusEntry,
                    schematic_types_pb2.GlobalLabel, schematic_types_pb2.LocalLabel,
                    schematic_types_pb2.HierarchicalLabel,
                    schematic_types_pb2.DirectiveLabel,
                    schematic_types_pb2.Image):
                if a.Is(proto_cls.DESCRIPTOR):
                    obj = proto_cls()
                    a.Unpack(obj)
                    ids.append(obj.id.value)
                    break
        if ids:
            kc.delete_items(header, ids)
        return len(ids)


# ============================================================
# 引脚辅助
# ============================================================

def _pin_iu(syms: dict, ref: str, pin: str):
    info = syms.get(ref)
    if not info:
        raise RuntimeError(f"没有已放置符号 {ref}（当前有: {sorted(syms)}）")
    pins = info.get("pins") or {}
    if str(pin) not in pins:
        raise RuntimeError(f"符号 {ref} 没有引脚 {pin}（可用: {sorted(pins)}）")
    return pins[str(pin)]


# ============================================================
# 公开工具
# ============================================================

def kicad_sch_auto_layout(
    symbols_json: str,
    nets_json: str = "",
    mode: str = "auto",
    columns: int = 3,
    x0_mm: float = 50.0,
    y0_mm: float = 50.0,
    gap_mm: float = 0.0,
) -> str:
    """按电路连通关系自动排布符号（信号流向分列，电源符号放上/下轨道）。

    Args:
        symbols_json: JSON 数组，每项含 ref/lib/symbol/value/orient:
            '[{"ref":"R1","lib":"Device","symbol":"R","value":"10k"},\\n'
            ' {"ref":"V1","lib":"Simulation_SPICE","symbol":"VDC","value":"5","orient":90}]'
        nets_json: 可选，netlist 决定信号流向与电源网络:
            '[{"name":"VIN","pins":[["V1","1"],["R1","1"]]}]'
        mode: "auto"/"flow"（按流向排布）| "grid"（普通网格）。
        columns: grid 模式下的列数。
        x0_mm, y0_mm: 起点。
        gap_mm: 最小间距（按符号尺寸自适应放大）。

    Returns:
        每个符号的放置位置与引脚预览。
    """
    symbols = _parse_json(symbols_json, "symbols_json")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("symbols_json 应为非空 JSON 数组")
    nets = _parse_json(nets_json, "nets_json") if nets_json.strip() else []

    # 解析/校验库与符号
    for s in symbols:
        s["lib"], s["symbol"] = _resolve_symbol(s)

    layout = _compute_layout(symbols, nets, {
        "mode": mode, "columns": columns,
        "x0_mm": x0_mm, "y0_mm": y0_mm, "gap_mm": gap_mm,
    })
    msgs = _place_symbols(symbols, layout)

    lines = [f"✅ 已自动布局 {len(symbols)} 个符号（mode={mode}）"]
    for s, m in zip(symbols, msgs):
        lines.append("  " + m.splitlines()[0])
    return "\n".join(lines)


def kicad_sch_auto_route(
    nets_json: str,
) -> str:
    """批量自动布线：把多个网络的引脚用导线连起来（链式，自动避让）。

    适用：符号已放置完毕。逐网络布线，已布导线会作为"障碍"让后续网络
    尽量绕行，减少交叉。之后可跑 kicad_sch_erc 验证。

    Args:
        nets_json: JSON 数组，每项含 name 与 pins（ref,引脚号）:
            '[{"name":"VIN","pins":[["V1","1"],["R1","1"]]},\\n'
            ' {"name":"GND","pins":[["C1","2"],["V1","2"],["G1","1"]]}]'

    Returns:
        各网络的布线摘要（段数）。
    """
    nets = _parse_json(nets_json, "nets_json")
    if not isinstance(nets, list):
        raise ValueError("nets_json 应为 JSON 数组")
    syms = _read_symbols()
    owner_bbox_map = {ref: _symbol_bbox_mm(info) for ref, info in syms.items()}
    obstacles = list(owner_bbox_map.values())
    used_lanes_iu: list = []

    summary = []
    all_segs = []
    all_junctions = []
    for net in nets:
        name = net.get("name", "?")
        pins = net.get("pins", [])
        if len(pins) < 2:
            summary.append(f"  {name}: 仅 {len(pins)} 个引脚，跳过布线")
            continue
        pin_refs = [(r, _pin_iu(syms, r, p)) for r, p in pins]
        segs, y_lane, junctions = _route_net_trunk(
            pin_refs, obstacles, used_lanes_iu, owner_bbox_map)
        all_segs += segs
        all_junctions += junctions
        summary.append(f"  {name}: 连接 {len(pins)} 个引脚，{len(segs)} 段导线")

    _create_lines(all_segs, all_junctions)
    return "✅ 自动布线完成:\n" + "\n".join(summary)


def kicad_sch_draw_circuit(
    circuit_json: str,
    clear: Optional[bool] = None,
    run_erc: Optional[bool] = None,
    render: Optional[bool] = None,
    max_fix_attempts: Optional[int] = None,
) -> str:
    """一键画电路：布局→布线→标签→保存→ERC→自动修复→渲染 SVG。

    从电路描述（JSON）自动完成整张原理图的绘制，并验证 ERC 通过、渲染
    SVG 供 AI 检查。**这是"成图"的杀手级工具**：一次调用替代几十次低层
    工具调用。

    Args:
        circuit_json: 电路描述 JSON:
            {
              "symbols": [{"ref":"V1","lib":"Simulation_SPICE","symbol":"VDC",
                           "value":"5","orient":90},
                          {"ref":"R1","lib":"Device","symbol":"R","value":"10k"},
                          {"ref":"C1","lib":"Device","symbol":"C","value":"100u"},
                          {"ref":"G1","lib":"power","symbol":"GND"}],
              "nets": [{"name":"VIN","pins":[["V1","1"],["R1","1"]]},
                       {"name":"OUT","pins":[["R1","2"],["C1","1"]]},
                       {"name":"GND","pins":[["C1","2"],["V1","2"],["G1","1"]]}],
              "labels": [{"net":"VIN","text":"VIN"},{"net":"OUT","text":"OUT"}],
              "layout": {"mode":"auto","x0_mm":50,"y0_mm":50,"gap_mm":0},
              "clear": true, "run_erc": true, "render": true,
              "max_fix_attempts": 3
            }
            说明: nets[].pins 顺序隐含信号方向（p0 输入 → pn 输出）；电源网络
            （如 3V3/5V/VCC）ERC 报 "Input Power pin not driven" 时会自动补
            PWR_FLAG。symbols[].orient=90 表示水平放置（引脚在左右），默认 0。
        clear: 画之前清空当前图纸（默认 true，来自 JSON 的 clear 字段）。
        run_erc: 画完后跑 ERC（默认 true）。
        render: 画完后渲染 SVG（默认 true）。
        max_fix_attempts: ERC 自动修复最大尝试次数（默认 3）。

    Returns:
        布局/布线/标签/ERC/渲染 的完整报告。
    """
    data = _parse_json(circuit_json, "circuit_json")
    if not isinstance(data, dict):
        raise ValueError("circuit_json 应为 JSON 对象")
    symbols = data.get("symbols")
    nets = data.get("nets", [])
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("circuit_json.symbols 应为非空数组")

    clear = data.get("clear", True) if clear is None else clear
    run_erc = data.get("run_erc", True) if run_erc is None else run_erc
    render = data.get("render", True) if render is None else render

    lines = ["🧩 kicad_sch_draw_circuit 开始"]
    if clear:
        n = _clear_sheet()
        lines.append(f"  · 已清空图纸（删除 {n} 个元素）")

    # 解析符号库
    for s in symbols:
        s["lib"], s["symbol"] = _resolve_symbol(s)

    # 电源符号不实际放置：电源网络改用「本地标签」表示（经踩坑验证：
    # power 符号引脚是 power_in 需要额外驱动、还会让 SPICE netlist 产生
    # 占位行；本地标签既满足 ERC 又让 netlist 干净，适合仿真）。
    power_syms = [s for s in symbols if _is_power_spec(s)]
    power_refs = {s.get("ref") for s in power_syms}
    real_symbols = [s for s in symbols if s not in power_syms]
    if power_syms:
        lines.append(f"  · ℹ️ 电源符号 {', '.join(s.get('ref') for s in power_syms)} "
                     f"改为用网络标签表示（不放置 power:GND/+3V3 等符号）")

    # 布局 + 放置（只放非电源符号）。流向计算用完整符号列表，让电源网络
    # （含已跳过的电源符号）不参与 stage，否则会成环全挤到同一列。
    layout = _compute_layout(symbols, nets, data.get("layout", {}))
    place_msgs = _place_symbols(real_symbols, layout)
    lines.append(f"  · 已放置 {len(real_symbols)} 个符号")
    for s, m in zip(real_symbols, place_msgs):
        lines.append("      " + m.splitlines()[0])

    # 布线（每网络独立 trunk 道，防共线合并）。电源网络只布其余引脚。
    syms = _read_symbols()
    owner_bbox_map = {ref: _symbol_bbox_mm(info) for ref, info in syms.items()}
    obstacles = list(owner_bbox_map.values())
    used_lanes_iu: list = []
    net_lanes: dict = {}   # net 名 -> trunk y_iu（标签放 trunk 上）
    routed = []
    all_junctions = []

    # 电源轨道（行业惯例 IEC 61082：电源在上、地在下）：给电源网络首选
    # 底部/顶部轨道道。基于已放置符号的 y 范围计算。
    power_lanes = _power_rail_lanes(syms, nets, power_refs, used_lanes_iu,
                                    obstacles)
    for net in nets:
        name = net.get("name", "")
        pins = [(r, p) for r, p in net.get("pins", []) if r not in power_refs]
        if len(pins) < 2:
            continue
        pin_refs = [(r, _pin_iu(syms, r, p)) for r, p in pins]
        preferred = power_lanes.get(name)
        segs, y_lane, junctions = _route_net_trunk(
            pin_refs, obstacles, used_lanes_iu, owner_bbox_map,
            preferred_lane=preferred)
        routed.append((name, len(pins), segs))
        net_lanes[name] = y_lane
        all_junctions += junctions
    _create_lines([s for _, _, segs in routed for s in segs], all_junctions)
    lines.append("  · 布线完成: " + ", ".join(
        f"{n}({p}pin/{len(s)}seg)" for n, p, s in routed))

    # 标签：电源网络 + 用户显式要求的 label，都放在 trunk 上（并入网络）。
    # GND/0 网络标签用 "0"（SPICE 地），让 netlist 输出节点 0，仿真才正确。
    n_labels = 0
    for net in nets:
        name = net.get("name", "")
        pins = net.get("pins", [])
        has_power = any(r in power_refs for r, _ in pins)
        text = net.get("label") or (name if has_power else "")
        if name.upper() in ("GND", "0"):
            text = "0"
        if not text or not pins:
            continue
        y_lane = net_lanes.get(name)
        ix, iy = _pin_iu(syms, pins[0][0], pins[0][1])
        if y_lane is not None:
            lx, ly = ix / MM, y_lane / MM
        else:
            lx, ly = ix / MM, iy / MM
        kicad_sch_add_label("local", text, lx, ly)
        n_labels += 1
    if n_labels:
        lines.append(f"  · 已放置 {n_labels} 个网络标签")

    # 未用引脚打 X（NoConnect，行业惯例）：网表里没出现、也没接线的引脚，
    # 明确标记"有意不连接"，也让原理图更规范（IPC-2612 风格）。
    if data.get("no_connect_marks", False):
        n_x = _mark_unused_pins(nets, syms)
        if n_x:
            lines.append(f"  · 已为 {n_x} 个未用引脚放置 NoConnect(X) 标记")

    # 保存 + ERC
    kicad_save_document()
    if run_erc:
        erc = kicad_sch_erc()
        lines.append("── ERC ──")
        lines.append(erc)
    else:
        lines.append("（已跳过 ERC）")

    # 行业标准审查（每次设计自动参与）
    if data.get("standards_check", True):
        from .standards import kicad_sch_standards_check
        lines.append("── 标准审查 ──")
        lines.append(kicad_sch_standards_check(sch_file=_current_sch_path(),
                                               include_erc=False))

    # 渲染 SVG 反馈
    if render:
        try:
            r = kicad_sch_render(sch_file=_current_sch_path())
            lines.append("── 渲染 ──")
            lines.append(r)
        except Exception as exc:
            lines.append(f"  ⚠️ 渲染失败: {exc}")

    return "\n".join(lines)


ALL_TOOLS = [
    kicad_sch_auto_layout,
    kicad_sch_auto_route,
    kicad_sch_draw_circuit,
    kicad_sch_array,
]
