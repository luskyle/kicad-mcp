"""L4 Golden 回归：把已验证电路的电气结构（netlist 连通性 + 标签）存 golden，
重画/改动后对比，防止"能画但画错/漏连"的回归。

核心思路：netlist 的**网络连通性**（哪个引脚在哪个网络）是原理图正确性的
最可靠判据 —— 比像素/坐标对比强（布局变美了、连线绕道了都不影响连通性，
只要电气上还连得对就行）。

数据存放：tests/golden/<name>.golden.json
  {
    "name": "rc",
    "nets": {"VIN": [["V1","1"],["R1","1"]], ...},   # 每网络节点(ref,pin)排序
    "labels": ["0","OUT","VIN", ...],                # 网络标签（去重排序）
    "meta": {...}                                    # 生成时间/来源
  }

对比时忽略 netlist 里 KiCad 自动生成的电源节点（如 GND1 __GND1 占位）、
和 power 符号自身（PWR_FLAG 会出现在 netlist，但跨版本稳定，保留对比）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from .tools.quality import _export_netlist

GOLDEN_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "golden"


# ---------------------------------------------------------------------------
# 提取
# ---------------------------------------------------------------------------

def extract_connectivity(sch_file: str) -> dict:
    """导出 netlist 并返回 {net_name: sorted[(ref, pin)]}。"""
    nets = _export_netlist(sch_file)
    out = {}
    for n in nets:
        nodes = sorted((nd["ref"], nd["pin"]) for nd in n["nodes"] if nd["ref"])
        out[n["name"]] = nodes
    return out


def extract_labels(sch_file: str) -> list:
    """从 .kicad_sch 提取所有网络标签文本（global/local/hier 去重排序）。

    注意：KiCad 文件里 local label 的 S-expr 是 `(label ".."`（不是 local_label），
    global 是 `(global_label ".."`、hier 是 `(hier_label ".."`。
    """
    txt = Path(sch_file).read_text(errors="ignore")
    found = set()
    for m in re.finditer(r'\((label|global_label|local_label|hier_label) "([^"]+)"', txt):
        found.add(m.group(2))
    return sorted(found)


def make_golden(name: str, sch_file: str, meta: Optional[dict] = None) -> dict:
    """从已验证原理图生成 golden 数据。"""
    return {
        "name": name,
        "nets": extract_connectivity(sch_file),
        "labels": extract_labels(sch_file),
        "meta": {"source": str(sch_file), **(meta or {})},
    }


def save_golden(name: str, golden: dict) -> str:
    """保存 golden 到 tests/golden/<name>.golden.json。"""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = GOLDEN_DIR / f"{name}.golden.json"
    path.write_text(json.dumps(golden, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def load_golden(name: str) -> dict:
    path = GOLDEN_DIR / f"{name}.golden.json"
    if not path.exists():
        raise FileNotFoundError(f"没有 golden 文件: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 对比
# ---------------------------------------------------------------------------

def compare(sch_file: str, golden: dict) -> tuple:
    """对比当前原理图 vs golden，返回 (通过?, 报告行列表)。

    只对比 golden 里记录过的网络（新画的网络不做要求，避免过度约束）。
    """
    cur_nets = extract_connectivity(sch_file)
    cur_labels = extract_labels(sch_file)

    exp_nets = golden.get("nets", {})
    exp_labels = golden.get("labels", [])

    lines = []
    ok = True

    # 1) 每个 golden 网络都必须存在且节点完全一致（统一成 (ref,pin) 元组比较，
    #    JSON 反序列化后是 list，运行时是 tuple）
    def _norm(nodes) -> list:
        return sorted((str(a), str(b)) for a, b in nodes)

    for net, exp_raw in sorted(exp_nets.items()):
        exp_nodes = _norm(exp_raw)
        cur_nodes = _norm(cur_nets.get(net, []))
        if cur_nodes == exp_nodes:
            lines.append(f"  ✅ 网络 {net}: {len(cur_nodes)} 节点一致")
        else:
            ok = False
            lines.append(f"  ❌ 网络 {net}: 不一致")
            lines.append(f"     期望: {exp_nodes}")
            lines.append(f"     当前: {cur_nodes}")

    # 2) 标签集合（golden 里的标签必须都还在）
    missing = [l for l in exp_labels if l not in cur_labels]
    if missing:
        ok = False
        lines.append(f"  ❌ 缺失标签: {missing}")
    else:
        lines.append(f"  ✅ 标签 {len(exp_labels)} 个全部存在")

    return ok, lines


def check_golden(name: str, sch_file: str) -> str:
    """运行一个 golden 对比，返回可读报告。"""
    golden = load_golden(name)
    ok, lines = compare(sch_file, golden)
    head = f"🔍 Golden 回归 [{name}]: " + ("✅ PASS" if ok else "❌ FAIL")
    return "\n".join([head, *lines])


def check_all_golden(sch_map: dict) -> str:
    """批量对比多个 (name -> sch_file)，返回汇总报告。"""
    out = []
    all_ok = True
    for name, sch in sch_map.items():
        try:
            r = check_golden(name, sch)
            out.append(r)
            if "❌ FAIL" in r:
                all_ok = False
        except Exception as exc:
            all_ok = False
            out.append(f"🔍 Golden 回归 [{name}]: ❌ 运行异常: {exc}")
    out.insert(0, "=" * 40)
    out.insert(1, f"🏁 Golden 回归汇总: " + ("全部通过 ✅" if all_ok else "存在失败 ❌"))
    out.insert(2, "=" * 40)
    return "\n".join(out)
