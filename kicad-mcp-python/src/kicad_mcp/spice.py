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


# ---------------- kicad-cli 导出 ----------------


def find_kicad_cli() -> str:
    env = os.environ.get("KICAD_CLI")
    if env:
        return env
    for c in [
        "/media/luskyle/DATA/project/kicad-mcp/build/kicad/kicad-cli",
        "/usr/local/bin/kicad-cli",
        "/usr/bin/kicad-cli",
    ]:
        if os.path.exists(c):
            return c
    return "kicad-cli"


def export_spice_netlist(sch_file: str) -> str:
    """用 kicad-cli 把原理图导出为 SPICE netlist 文本。"""
    kicad_cli = find_kicad_cli()
    env = dict(os.environ)
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    for k in ("CONDA_PREFIX", "CONDA_DEFAULT_ENV", "PYTHONHOME", "PYTHONPATH"):
        env.pop(k, None)
    env.setdefault("KICAD_STOCK_DATA_HOME", "/tmp/squashfs-root/share/kicad")

    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "net.spice")
        proc = subprocess.run(
            [kicad_cli, "sch", "export", "netlist", "--format", "spice",
             sch_file, "-o", out],
            capture_output=True, text=True, env=env, timeout=120,
        )
        if not os.path.exists(out):
            raise RuntimeError(
                f"SPICE netlist 导出失败 (exit {proc.returncode}): "
                f"{(proc.stderr or proc.stdout).strip()[:500]}"
            )
        return open(out, encoding="utf-8").read()
