"""SPICE 电路仿真模块：把 KiCad 原理图导出为 SPICE netlist 并用 ngspice 仿真。

依赖：
- kicad-cli（导出 spice netlist）
- libngspice.so.0（本机已装 libngspice0，无需 ngspice CLI / sudo）

流程：
1. kicad-cli sch export netlist --format spice 导出 netlist
2. 预处理：删除 power 符号占位行（`GND1 __GND1` 等 1 端无模型器件）、
   把 GND 网络名映射为节点 0
3. 用 ctypes 加载 libngspice，ngSpice_Init -> source -> run -> wrdata 写波形
4. 解析波形文件，返回各向量的时间序列与统计

关键陷阱（已实测）：
- 初始化必须用 ngSpice_Init（7 个回调参数），不是 ngSpice_Init_Sync（5 参，
  用于外部电压源同步）。回调返回 int。
- SendChar / SendStat 回调必须提供，否则 ngspice 打印时调用 NULL 函数指针
  导致段错误。
- KiCad netlist 的 `GND1 __GND1` 类 power 占位行在 ngspice 中报 bad syntax，
  必须删除；GND 网络名 "GND" 需替换为节点 0。
- ngspice 的 .tran 默认用 DC 工作点做初始条件，RC 充电需加 `.tran ... UIC`
  或 `.ic` 指令。
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import sys
import tempfile
from .runtime import find_kicad_cli as runtime_find_kicad_cli, kicad_cli_env
from pathlib import Path

# ---------------- ngspice 调用 ----------------

SENDCHAR = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
SENDSTAT = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
CONTROLLED_EXIT = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p
)
SENDDATA = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
SENDINITDATA = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
BGTHREAD = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)

_ngspice_lib = None
_ngspice_log: list[str] = []


def _get_lib():
    global _ngspice_lib
    if _ngspice_lib is None:
        _ngspice_lib = ctypes.CDLL("libngspice.so.0")
    return _ngspice_lib


@SENDCHAR
def _send_char(s, ident, user):
    if s:
        txt = s.decode("utf-8", "replace")
        if txt.strip():
            _ngspice_log.append(txt)
    return 0


@SENDSTAT
def _send_stat(s, ident, user):
    if s:
        txt = s.decode("utf-8", "replace")
        if txt.strip():
            _ngspice_log.append(txt)
    return 0


@CONTROLLED_EXIT
def _controlled_exit(status, immediate, on_quit, ident, user):
    _ngspice_log.append(f"[ngspice 请求退出] status={status}")
    return 0


@SENDDATA
def _send_data(data, nplots, nvects, user):
    return 0


@SENDINITDATA
def _send_init_data(data, nplots, user):
    return 0


@BGTHREAD
def _bg_thread(running, ident, user):
    return 0


def _ngspice_init() -> None:
    """初始化 libngspice（必须用 ngSpice_Init，7 回调）。"""
    lib = _get_lib()
    fn = lib.ngSpice_Init
    fn.argtypes = [ctypes.c_void_p] * 7
    fn.restype = ctypes.c_int
    fn(_send_char, _send_stat, _controlled_exit, _send_data, _send_init_data,
       _bg_thread, None)


def _ngspice_command(cmd: str) -> int:
    lib = _get_lib()
    lib.ngSpice_Command.argtypes = [ctypes.c_char_p]
    lib.ngSpice_Command.restype = ctypes.c_int
    return lib.ngSpice_Command(cmd.encode("utf-8"))


# ---------------- netlist 处理 ----------------

POWER_PLACEHOLDER_RE = re.compile(r"^\w+\s+__\w+\s*$")


def preprocess_netlist(text: str, extra_lines: list[str] | None = None) -> str:
    """清洗 KiCad 导出的 SPICE netlist，返回可直接喂给 ngspice 的文本。

    - 删除 power 符号占位行（`GND1 __GND1`、`PWR1 __PWR1` 等 1 端无模型器件）
    - 节点名 GND -> 0（接地）
    - 在 .end 前追加 extra_lines（如 `.ic v(/OUT)=0`）
    """
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if POWER_PLACEHOLDER_RE.match(stripped):
            continue
        # 节点 token GND -> 0
        line = re.sub(r"\bGND\b", "0", line)
        out.append(line)
    if extra_lines:
        if ".end" in out:
            out.insert(out.index(".end"), *extra_lines)
        else:
            out.extend(extra_lines)
    return "\n".join(out) + "\n"


def extract_nodes(netlist_text: str) -> list[str]:
    """从 netlist 提取非地、非内部节点名（用于构造观测向量）。"""
    _NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?([a-zA-Z]+)?$")
    _SKIP = {"0", "DC", "AC", "TRAN", "UIC"}
    nodes: set[str] = set()
    for line in netlist_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(".") or stripped.startswith("*"):
            continue
        toks = stripped.split()
        if len(toks) < 3:
            continue
        for tok in toks[1:]:
            if tok in _SKIP or _NUM.match(tok):
                continue  # 数值 / 带单位的值（如 100u、1k）/ 关键字
            if tok.startswith("__"):
                continue
            if "#" in tok or "+" in tok:
                continue
            nodes.add(tok)
    return sorted(nodes)


# ---------------- 仿真主流程 ----------------


def run_ngspice(netlist_text: str, vectors: list[str],
                extra_lines: list[str] | None = None) -> dict:
    """运行 ngspice 瞬态/DC 仿真，返回各向量数据。

    Returns:
        {"vectors": {name: {"time": [...], "data": [...]}},
         "log": [...], "rows": int}
    """
    global _ngspice_log
    _ngspice_log = []
    clean = preprocess_netlist(netlist_text, extra_lines)

    with tempfile.TemporaryDirectory() as td:
        net_path = Path(td) / "circuit.cir"
        out_path = Path(td) / "wave.txt"
        net_path.write_text(clean)

        _ngspice_init()
        r1 = _ngspice_command(f"source {net_path}")
        r2 = _ngspice_command("run")
        # 写全部观测向量（含 scale 列，每向量 2 列：scale + data）
        r3 = _ngspice_command(f"wrdata {out_path} {' '.join(vectors)}")

        if not out_path.exists():
            log = "".join(_ngspice_log)[-2000:]
            raise RuntimeError(f"仿真未产生输出。ngspice 日志:\n{log}")

        # 解析: 每行 scale, v1, scale, v2, ...（每向量前有 scale 列）
        parsed: dict[str, list[float]] = {v: [] for v in vectors}
        times: list[float] = []
        with open(out_path) as f:
            for line in f:
                vals = [float(x) for x in line.split()]
                if len(vals) < 2:
                    continue
                times.append(vals[0])
                data = vals[1::2]
                for i, v in enumerate(vectors):
                    if i < len(data):
                        parsed[v].append(data[i])

        return {
            "vectors": {v: {"time": times, "data": parsed[v]} for v in vectors},
            "log": "".join(_ngspice_log),
            "rows": len(times),
        }


def stats_for(series: list[float]) -> dict:
    """向量统计：初值/末值/最大/最小/均值。"""
    if not series:
        return {}
    return {
        "initial": round(series[0], 6),
        "final": round(series[-1], 6),
        "min": round(min(series), 6),
        "max": round(max(series), 6),
        "avg": round(sum(series) / len(series), 6),
    }


def _is_saturated(times: list[float], data: list[float], tol_frac: float = 0.02) -> bool:
    """判断波形是否已接近稳态（尾部变化小）。未饱和时 τ 估计不可靠。"""
    if len(data) < 20:
        return True
    k = max(1, len(data) // 10)
    span = max(data) - min(data)
    if span < 1e-12:
        return True
    tail_change = abs(data[-1] - data[-k])
    return tail_change / span <= tol_frac


def _estimate_tau(times: list[float], data: list[float], v_start: float,
                  v_final: float, charging: bool) -> float | None:
    """对 RC 充/放电估计时间常数 τ（仅在波形接近稳态时可靠）。

    充电：v_start → v_final，τ = 达到 63.2% 幅度处的时间（从起始时刻算起）。
    放电：v_start → v_final，τ = 降到 36.8% 幅度处的时间。
    """
    if len(times) < 2 or len(data) != len(times):
        return None
    span = v_final - v_start
    if abs(span) < 1e-12:
        return None
    t0 = times[0]
    target = v_start + 0.632 * span if charging else v_start + 0.368 * span
    for i in range(1, len(data)):
        prev, cur = data[i - 1], data[i]
        if (prev - target) * (cur - target) <= 0:
            if abs(cur - prev) < 1e-12:
                return None
            frac = (target - prev) / (cur - prev)
            return (times[i - 1] + frac * (times[i] - times[i - 1])) - t0
    return None


def analyze_signal(name: str, times: list[float], data: list[float]) -> dict:
    """自动分析一个信号波形，返回分类、描述和关键参数。

    Returns:
        {"kind": "constant"|"rising"|"falling"|"oscillating",
         "desc": 人类可读描述, "params": {...}}
    """
    if not data:
        return {"kind": "unknown", "desc": f"{name}: 无数据", "params": {}}
    v0, vend = data[0], data[-1]
    vmin, vmax = min(data), max(data)
    span = vmax - vmin
    tol = max(span * 0.01, 1e-9)
    saturated = _is_saturated(times, data)

    if span <= tol:
        return {"kind": "constant",
                "desc": f"{name} 恒为 {v0:.4g} V（稳定/直流电源）",
                "params": {"value": v0, "saturated": True}}

    mono_up = all(data[i] <= data[i + 1] + tol for i in range(len(data) - 1))
    mono_dn = all(data[i] >= data[i + 1] - tol for i in range(len(data) - 1))
    delta = vend - v0

    if mono_up and delta > 0:
        p = {"v_start": round(v0, 6), "v_end": round(vend, 6),
             "saturated": saturated}
        if saturated:
            tau = _estimate_tau(times, data, v0, vmax, charging=True)
            if tau is not None:
                p["tau_s"] = round(tau, 6)
                desc = (f"{name} 从 {v0:.4g} V 上升至 {vend:.4g} V"
                        f"（充电，τ≈{tau:.4g} s）")
            else:
                desc = f"{name} 从 {v0:.4g} V 上升至 {vend:.4g} V（充电）"
        else:
            desc = (f"{name} 从 {v0:.4g} V 上升至 {vend:.4g} V"
                    f"（仍在充电，未达稳态，需延长仿真测 τ）")
        return {"kind": "rising", "desc": desc, "params": p}

    if mono_dn and delta < 0:
        p = {"v_start": round(v0, 6), "v_end": round(vend, 6),
             "saturated": saturated}
        if saturated:
            tau = _estimate_tau(times, data, v0, vmin, charging=False)
            if tau is not None:
                p["tau_s"] = round(tau, 6)
                desc = (f"{name} 从 {v0:.4g} V 降至 {vend:.4g} V"
                        f"（放电，τ≈{tau:.4g} s）")
            else:
                desc = f"{name} 从 {v0:.4g} V 降至 {vend:.4g} V（放电）"
        else:
            desc = (f"{name} 从 {v0:.4g} V 降至 {vend:.4g} V"
                    f"（仍在放电，未达稳态，需延长仿真测 τ）")
        return {"kind": "falling", "desc": desc, "params": p}

    return {"kind": "oscillating",
            "desc": f"{name} 在 {vmin:.4g}~{vmax:.4g} V 间变化"
                    f"（起始 {v0:.4g} V，末值 {vend:.4g} V）",
            "params": {"vmin": round(vmin, 6), "vmax": round(vmax, 6),
                       "saturated": saturated}}


def find_unsaturated(result: dict) -> list[str]:
    """返回结果中尚未稳定（需延长仿真才能测准 τ）的信号名。"""
    out = []
    for vec, vd in result["vectors"].items():
        a = analyze_signal(vec, vd["time"], vd["data"])
        if a["kind"] in ("rising", "falling") and not a["params"].get("saturated", True):
            out.append(vec)
    return out


_SPICE_SUFFIX = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3,
                 "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}


def _parse_spice_num(s: str) -> float | None:
    import re
    m = re.match(r"^([+-]?[\d.]+(?:e[+-]?\d+)?)\s*([a-zA-Z]*)$", s.strip())
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).lower()
    return val * _SPICE_SUFFIX.get(unit, 1.0)


def extend_tran(netlist: str, factor: float = 8.0) -> str:
    """把 netlist 里 .tran 的仿真时长延长 factor 倍，便于测量时间常数。"""
    out = []
    for line in netlist.splitlines():
        stripped = line.strip()
        if stripped.startswith(".tran"):
            toks = stripped.split()
            if len(toks) >= 3:
                tstep = _parse_spice_num(toks[1])
                tstop = _parse_spice_num(toks[2])
                if tstep and tstop:
                    new_stop = tstop * factor
                    new_line = f".tran {toks[1]} {new_stop:g}"
                    if len(toks) > 3:
                        new_line += " " + " ".join(toks[3:])
                    out.append(new_line)
                    continue
        out.append(line)
    return "\n".join(out)


def analyze_results(result: dict, title: str = "") -> list[str]:
    """对一次仿真结果做自动分析，返回多行人类可读结论。"""
    lines = [f"\n🔍 自动分析{('（' + title + '）') if title else ''}："]
    for vec, vd in result["vectors"].items():
        a = analyze_signal(vec, vd["time"], vd["data"])
        lines.append(f"  ▸ {a['desc']}")
        st = stats_for(vd["data"])
        if st:
            lines.append(f"      初值={st['initial']:.4g}  末值={st['final']:.4g}"
                         f"  min={st['min']:.4g}  max={st['max']:.4g}")
    return lines


def auto_analyze(netlist: str, vec_list: list[str],
                 max_extend_rounds: int = 3) -> list[str]:
    """运行仿真并自动分析；对未达稳态的充/放电信号迭代延长 .tran 测准 τ。

    Returns:
        多行分析结论。
    """
    lines = []
    current = netlist
    target = vec_list

    result = run_ngspice(current, target)
    lines += analyze_results(result)
    unsat = find_unsaturated(result)

    for _ in range(max_extend_rounds):
        if not unsat:
            break
        current = extend_tran(current)
        result = run_ngspice(current, unsat)
        lines += analyze_results(result, "延长仿真精确测量时间常数")
        unsat = find_unsaturated(result)

    if unsat:
        lines.append(f"   ⚠️ 以下信号即使延长仿真仍未稳定（可能需要更长时间或检查电路）: "
                     f"{', '.join(unsat)}")

    return lines


# ---------------- 电路分析与仿真类型自动推荐 ----------------

# SPICE 器件前缀 -> 器件类型中文名
DEVICE_TYPE_CN = {
    "V": "电压源", "I": "电流源",
    "R": "电阻", "C": "电容", "L": "电感", "K": "耦合电感",
    "D": "二极管", "Q": "三极管", "M": "MOSFET", "J": "JFET",
    "X": "子电路/运放", "E": "压控电压源", "G": "压控电流源",
    "F": "流控电流源", "H": "流控电压源", "B": "行为源",
}

# 独立源的关键字（决定激励类型）
_SRC_KW = ("DC", "AC", "SIN", "PULSE", "EXP", "PWL", "SFFM")

# 真正的仿真分析指令（.title/.end 等是 netlist 结构，不算）
_ANALYSIS_DIRECTIVES = {".tran", ".op", ".dc", ".ac", ".noise", ".fft",
                        ".sp", ".pz", ".tf", ".sens", ".disto"}

# 有标称值（阻容感）的器件前缀
_VALUE_PREFIXES = {"R", "C", "L"}


def parse_circuit(netlist: str) -> dict:
    """解析 SPICE netlist，返回器件清单和分析指令。

    Returns:
        {"devices": {prefix: [{"ref","nodes","args","value"}...]},
         "directives": [".tran", ...]}
    """
    devices: dict[str, list] = {}
    directives: list[str] = []
    for line in netlist.splitlines():
        l = line.strip()
        if not l or l.startswith("*") or l.startswith("//"):
            continue
        if l.startswith("."):
            dname = l.split()[0].lower()
            if dname in _ANALYSIS_DIRECTIVES:
                directives.append(dname)
            continue
        toks = l.split()
        if not toks:
            continue
        prefix = toks[0][0].upper()
        if prefix not in DEVICE_TYPE_CN:
            continue
        # 值 = 最后一个数值 token（仅对 R/C/L 有意义）
        value = None
        if prefix in _VALUE_PREFIXES:
            for tok in reversed(toks[1:]):
                if _parse_spice_num(tok) is not None:
                    value = tok
                    break
        devices.setdefault(prefix, []).append(
            {"ref": toks[0], "nodes": toks[1:3], "args": toks[1:], "value": value}
        )
    return {"devices": devices, "directives": directives}


def analyze_sources(devices: dict) -> dict:
    """分析独立源的类型与值。返回 {"types": set, "sources": [...], "has_ac": bool}。"""
    srcs = []
    src_types: set[str] = set()
    for prefix in ("V", "I"):
        for d in devices.get(prefix, []):
            args = d["args"]
            found = [kw for kw in _SRC_KW if any(a.upper().startswith(kw) for a in args)]
            # 按激励类型优先级判定（AC 最特殊，其次瞬态激励，最后 DC）
            priority = ["AC", "SIN", "SFFM", "PULSE", "PWL", "EXP", "DC"]
            src_type = next((kw for kw in priority if kw in found), "DC")
            src_types.add(src_type)
            srcs.append({"ref": d["ref"], "kind": prefix, "type": src_type,
                         "value": d["value"]})
    return {"types": src_types, "sources": srcs,
            "has_ac": "AC" in src_types, "has_sin": bool(src_types & {"SIN", "SFFM"}),
            "has_pulse": bool(src_types & {"PULSE", "PWL", "EXP"})}


def estimate_time_constant(devices: dict) -> float | None:
    """粗略估计时间常数：max(R)*max(C) 或 max(L)/min(R)（取大者）。"""
    rs = [_parse_spice_num(d["value"]) for d in devices.get("R", []) if d["value"]]
    cs = [_parse_spice_num(d["value"]) for d in devices.get("C", []) if d["value"]]
    ls = [_parse_spice_num(d["value"]) for d in devices.get("L", []) if d["value"]]
    r_max = max(rs) if rs else None
    c_max = max(cs) if cs else None
    l_max = max(ls) if ls else None
    cand = []
    if r_max and c_max:
        cand.append(r_max * c_max)
    if l_max and r_max:
        cand.append(l_max / r_max)
    return max(cand) if cand else None


def recommend_sim_command(devices: dict) -> dict:
    """根据电路拓扑自动推荐最合适的仿真类型与指令。

    Returns:
        {"type": "tran"|"op"|"dc"|"ac",
         "command": 具体 ngspice 指令文本,
         "reasons": [说明...]}
    """
    src = analyze_sources(devices)
    d = devices
    has = {k: bool(d.get(k)) for k in DEVICE_TYPE_CN}
    reasons: list[str] = []

    # 1) 交流小信号分析：有 AC 激励
    if src["has_ac"]:
        reasons.append("检测到 AC 激励源，适合交流小信号分析（频响/增益/带宽）")
        return {"type": "ac",
                "command": ".ac dec 10 1 1meg",
                "reasons": reasons}

    # 2) 正弦源：时域波形 + 频响都有意义，优先瞬态看波形
    if src["has_sin"]:
        tau = estimate_time_constant(d)
        tstop = max(tau * 5 if tau else 1e-3, 1e-3)
        reasons.append("检测到正弦/调频源，瞬态分析可查看时域波形")
        return {"type": "tran",
                "command": f".tran {tstop / 1000:g} {tstop:g} UIC",
                "reasons": reasons}

    # 3) 脉冲/阶跃激励：瞬态看响应
    if src["has_pulse"]:
        tau = estimate_time_constant(d)
        tstop = max(tau * 5 if tau else 1e-3, 1e-3)
        reasons.append("检测到脉冲/阶跃激励，瞬态分析可查看电路响应")
        return {"type": "tran",
                "command": f".tran {tstop / 1000:g} {tstop:g} UIC",
                "reasons": reasons}

    # 4) 动态元件（电容/电感）+ 直流源：上电瞬态
    if has["C"] or has["L"]:
        tau = estimate_time_constant(d)
        tstop = max(tau * 5 if tau else 1e-3, 1e-3)
        kind = []
        if has["C"]:
            kind.append("电容")
        if has["L"]:
            kind.append("电感")
        reasons.append(f"含{'+'.join(kind)}与直流源，瞬态分析可查看充放电/阶跃响应")
        return {"type": "tran",
                "command": f".tran {tstop / 1000:g} {tstop:g} UIC",
                "reasons": reasons}

    # 5) 非线性器件（二极管/晶体管）：工作点 + 直流扫描
    if has["D"] or has["Q"] or has["M"] or has["J"]:
        reasons.append("含非线性器件（二极管/晶体管），直流扫描可查看转移/伏安特性，"
                       "也可先用 .op 确认工作点")
        return {"type": "dc",
                "command": ".op\n.dc V1 0 5 0.05",
                "reasons": reasons}

    # 6) 纯阻性 + 直流源：直流工作点即可
    reasons.append("纯电阻/直流电路，直流工作点分析即可")
    return {"type": "op", "command": ".op", "reasons": reasons}


def detect_simulation(netlist: str) -> dict:
    """分析 netlist，检测已有仿真指令并自动推荐合适的仿真类型。

    Returns:
        {"has_directive": bool, "existing": [指令...],
         "devices_summary": [描述...], "sources": [...],
         "recommendation": {...}}
    """
    parsed = parse_circuit(netlist)
    devices, directives = parsed["devices"], parsed["directives"]
    src = analyze_sources(devices)

    devices_summary = []
    for prefix, items in devices.items():
        for it in items:
            desc = f"{it['ref']}: {DEVICE_TYPE_CN[prefix]}"
            if it["value"]:
                desc += f" {it['value']}"
            devices_summary.append(desc)

    has_dir = bool(directives)
    return {
        "has_directive": has_dir,
        "existing": directives,
        "devices_summary": devices_summary,
        "sources": src["sources"],
        "recommendation": None if has_dir else recommend_sim_command(devices),
    }


# ---------------- kicad-cli 导出 ----------------


def find_kicad_cli() -> str:
    return runtime_find_kicad_cli()


def export_spice_netlist(sch_file: str) -> str:
    """用 kicad-cli 把原理图导出为 SPICE netlist 文本。"""
    kicad_cli = find_kicad_cli()

    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "net.spice")
        proc = subprocess.run(
            [kicad_cli, "sch", "export", "netlist", "--format", "spice",
             sch_file, "-o", out],
            capture_output=True, text=True, env=kicad_cli_env(), timeout=120,
        )
        if not os.path.exists(out):
            raise RuntimeError(
                f"SPICE netlist 导出失败 (exit {proc.returncode}): "
                f"{(proc.stderr or proc.stdout).strip()[:500]}"
            )
        return open(out, encoding="utf-8").read()
