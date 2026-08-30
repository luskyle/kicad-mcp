"""L4 质量门禁：ERC 门禁 + 违规自修复重试（保证"交付即通过"）。

这是做图能力提升方案（docs/drawing-improvement-plan.md）的 L4 层。
把"画完图要人工跑 ERC"变成工具内部的**自动门禁**：

  1) 跑 KiCad 官方 ERC，结构化解析（severity/描述/位置），不只给文本
  2) 违规分类：blocking（必须为 0）/ fixable（自动修复）/ benign（豁免）/ warning
  3) fixable（电源网络 power_in 未驱动）→ 自动补 PWR_FLAG 并接线 → 重跑，
     最多 max_attempts 轮
  4) 输出 PASS/FAIL + 修复记录 + 违规明细

分类规则（基于 ERC 语义 + 多页工程实际）：
  - **blocking**（error 且不可豁免）：Pin/Wire/Label not connected、off-grid、
    短路、电源网络未驱动（若自动修复失败）
  - **benign**（豁免，不阻塞）：Label 只连一个引脚（跨页标签的正常形态）、
    封装库缺失（环境问题）、"Input pin not driven"（跨页数字输入，由别的页驱动）
  - **warning**：其它 warning，只报告不阻塞
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Optional

from ..symbols import parse_sexpr
from .common import kicad_save_document
from .schematic import (
    MM,
    _current_sch_path,
    _find_kicad_cli,
    _read_symbols,
    kicad_sch_add_line,
    kicad_sch_add_symbol,
)

# 良性违规（可豁免，不阻塞交付）
_BENIGN_DESC = (
    "Label connected to only one pin",          # 跨页标签：本页只出现一次
    "当前配置中不包含封装库",                     # 封装库缺失（环境/库问题，非绘制）
    "Input pin not driven by any Output pins",  # 跨页数字输入（由其它页驱动）
    "Text variable not defined",
)

# blocking 违规（必须为 0；"Input Power pin not driven" 会先尝试自动修复）
_BLOCKING_DESC = (
    "Pin not connected",
    "Wire end not connected",
    "Label not connected",
    "off connection grid",
    "off grid",
    "connected to more than one",     # 一条线连到多个引脚/网络（短路）
    "电源输出和电源输出已连接",          # 两个 power_out 同网
    "Input Power pin not driven",     # 电源网络未驱动（先自动补 PWR_FLAG）
)


def _kicad_cli_env() -> dict:
    """隔离 Python 环境，并按平台设置 KiCad CLI 运行环境。"""
    env = dict(os.environ)
    for k in ("CONDA_PREFIX", "CONDA_DEFAULT_ENV", "PYTHONHOME", "PYTHONPATH"):
        env.pop(k, None)
    if os.name != "nt":
        env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        env.setdefault("KICAD_STOCK_DATA_HOME", "/tmp/squashfs-root/share/kicad")
    return env


def _run_cli(args: list, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True,
                          env=_kicad_cli_env(), timeout=timeout)


def _erc_violations(sch_file: str) -> list:
    """跑 KiCad 官方 ERC，返回结构化违规 [{severity,description,items:[str]}]。"""
    tmp = tempfile.mktemp(suffix=".json")
    try:
        proc = _run_cli([_find_kicad_cli(), "sch", "erc", "--format", "json",
                         "--severity-all", sch_file, "-o", tmp])
        if not os.path.exists(tmp):
            raise RuntimeError((proc.stderr or proc.stdout).strip()[:300])
        data = json.load(open(tmp, encoding="utf-8"))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    out = []
    for sheet in data.get("sheets", []):
        for v in sheet.get("violations", []):
            out.append({
                "severity": v.get("severity", "").lower(),
                "description": v.get("description", ""),
                "items": [it.get("description", "") for it in v.get("items", [])],
            })
    return out


def _export_netlist(sch_file: str) -> list:
    """kicad-cli 导出 netlist(kicadsexpr)，解析成 [{name, nodes:[{ref,pin,pintype}]}]。"""
    tmp = tempfile.mktemp(suffix=".net")
    try:
        proc = _run_cli([_find_kicad_cli(), "sch", "export", "netlist",
                         "--format", "kicadsexpr", sch_file, "-o", tmp])
        if not os.path.exists(tmp):
            raise RuntimeError((proc.stderr or proc.stdout).strip()[:300])
        root = parse_sexpr(open(tmp, encoding="utf-8").read())
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    def _iter(node, tag):
        if isinstance(node, list):
            if node and node[0] == tag:
                yield node
            for c in node:
                yield from _iter(c, tag)

    nets = []
    for net in _iter(root, "net"):
        name, nodes = "", []
        for item in net:
            if isinstance(item, list) and item and item[0] == "name" and len(item) > 1:
                name = str(item[1])
            elif isinstance(item, list) and item and item[0] == "node":
                nd = {"ref": "", "pin": "", "pintype": ""}
                for sub in item:
                    if isinstance(sub, list) and len(sub) > 1:
                        if sub[0] == "ref":
                            nd["ref"] = str(sub[1])
                        elif sub[0] == "pin":
                            nd["pin"] = str(sub[1])
                        elif sub[0] == "pintype":
                            nd["pintype"] = str(sub[1])
                nodes.append(nd)
        if name or nodes:
            nets.append({"name": name, "nodes": nodes})
    return nets


def _nets_need_pwrflag(nets: list) -> list:
    """返回含 power_in 节点但无 power_out 节点的网络名（电源未驱动，需补 PWR_FLAG）。

    注意：由普通 output（如 LDO 输出）驱动的网络不在此列 —— 它没有 power_in
    引脚需要 power_out 驱动，硬加 PWR_FLAG 反而报"电源输出和电源输出已连接"。
    """
    out = []
    for n in nets:
        has_in = any(nd["pintype"] == "power_in" for nd in n["nodes"])
        has_out = any(nd["pintype"] == "power_out" for nd in n["nodes"])
        if has_in and not has_out:
            out.append(n["name"])
    return out


def _add_pwr_flag(net_name: str) -> str:
    """给未驱动的电源网络补一个 power:PWR_FLAG 并接线，返回消息。

    依赖当前 eeschema 打开的文档（API 放置/连线），需要先保存过。
    """
    syms = _read_symbols()
    nets = _export_netlist(_current_sch_path())
    target = None
    for n in nets:
        if n["name"] != net_name:
            continue
        for nd in n["nodes"]:
            if nd["pintype"] in ("power_in", "passive") and nd["ref"] in syms:
                target = nd
                break
        if target:
            break
    if target is None:
        for n in nets:
            if n["name"] != net_name or not n["nodes"]:
                continue
            for nd in n["nodes"]:
                if nd["ref"] in syms:
                    target = nd
                    break
            if target:
                break
    if target is None:
        raise RuntimeError(f"找不到网络 {net_name} 的可连引脚")
    pin_pos = (syms[target["ref"]].get("pins") or {}).get(str(target["pin"]))
    if pin_pos is None:
        raise RuntimeError(f"符号 {target['ref']} 无引脚 {target['pin']}")
    px_mm, py_mm = pin_pos[0] / MM, pin_pos[1] / MM

    # PWR_FLAG 连接点 = 符号中心；在上/下逐级找不重叠的空位。
    # 符号 bbox 含 3.81mm padding，5.08 仍会叠在紧凑 IC 上，需更大距离。
    from .schematic import _snap_grid
    flag_y = None
    for dy in (-5.08, 5.08, -8.89, 8.89, -12.7, 12.7, 0.0):
        try:
            fy = _snap_grid(py_mm + dy)
            kicad_sch_add_symbol("power", "PWR_FLAG", px_mm, fy,
                                 value="PWR_FLAG",
                                 snap_to_grid=True, avoid_overlap=True)
            flag_y = fy
            break
        except Exception:
            continue
    if flag_y is None:
        raise RuntimeError(f"网络 {net_name} 附近没有空位放 PWR_FLAG")

    # 连线：PWR_FLAG 连接点 -> 目标引脚（2.54mm 竖线，两端都是端点）
    if abs(flag_y - py_mm) > 0.01:
        kicad_sch_add_line(px_mm, flag_y, px_mm, py_mm)
    return (f"已为电源网络 {net_name} 补 PWR_FLAG "
            f"@({px_mm:.2f},{flag_y:.2f})mm → 连到 {target['ref']}.{target['pin']}")


def _classify(violations: list) -> tuple:
    """把违规分为 (blocking, benign, warning) 三组。"""
    blocking, benign, warns = [], [], []
    for v in violations:
        desc, sev = v["description"], v["severity"]
        d = desc.lower()
        if any(k.lower() in d for k in _BENIGN_DESC):
            benign.append(v)
        elif sev == "error":
            blocking.append(v)
        elif any(k.lower() in d for k in _BLOCKING_DESC):
            blocking.append(v)
        else:
            warns.append(v)
    return blocking, benign, warns


def _fmt_viol(v: dict) -> str:
    lines = [f"  [{v['severity']}] {v['description']}"]
    for it in v.get("items", [])[:4]:
        lines.append(f"        -> {it}")
    return "\n".join(lines)


def kicad_sch_erc_gate(
    sch_file: Optional[str] = None,
    fix: bool = True,
    max_attempts: int = 3,
    detailed: bool = True,
) -> str:
    """L4 质量门禁：跑 ERC → 自动修复 → 判定是否"交付即通过"。

    Args:
        sch_file: 原理图路径；不传用当前 eeschema 打开的文档（建议先保存）。
        fix: 是否自动修复（电源网络未驱动 → 补 PWR_FLAG，需 eeschema 打开）。
        max_attempts: 修复重试轮数（默认 3）。
        detailed: 是否输出完整违规明细（默认 True；False 只给结论）。

    Returns:
        PASS/FAIL 报告：修复记录 + 违规分组 + 结论。
    """
    sch = sch_file or _current_sch_path()
    lines = ["🧪 ERC 门禁（L4 · 交付即通过）"]
    all_fixes: list = []
    tried_fix = False

    for attempt in range(1, max_attempts + 1):
        violations = _erc_violations(sch)
        blocking, benign, warns = _classify(violations)

        # 自动修复：电源网络未驱动（含 power_in 但无 power_out）
        if fix and not tried_fix:
            try:
                nets = _export_netlist(sch)
                need = _nets_need_pwrflag(nets)
            except Exception as exc:
                need = []
                lines.append(f"  ⚠️ 无法解析 netlist（跳过自动修复）: {exc}")
            if need:
                ok = []
                for nm in need:
                    try:
                        all_fixes.append(_add_pwr_flag(nm))
                        ok.append(nm)
                    except Exception as exc:
                        lines.append(f"  ⚠️ 自动修复失败({nm}): {exc}")
                if ok:
                    try:
                        kicad_save_document()
                    except Exception:
                        pass
                    lines.append(f"  第{attempt}轮 · 已补 PWR_FLAG 到电源网络: "
                                 f"{', '.join(ok)}")
                    tried_fix = True
                    continue  # 重跑 ERC 确认
            tried_fix = True

        # 判定
        n_err = len(blocking)
        n_ben = len(benign)
        n_warn = len(warns)
        if n_err == 0:
            lines.append("✅ 门禁结果: **PASS**（无 blocking 违规）")
        else:
            lines.append(f"❌ 门禁结果: **FAIL**（{n_err} 条 blocking 违规）")
        if all_fixes:
            lines.append("  · 自动修复: " + "; ".join(all_fixes))
        lines.append(f"  · 违规统计: {n_err} blocking / {n_ben} 豁免 / {n_warn} warning")
        if detailed:
            if blocking:
                lines.append("  ── blocking（需处理）──")
                for v in blocking:
                    lines.append(_fmt_viol(v))
            if benign:
                lines.append("  ── 豁免项（不阻塞：跨页/标签/库）──")
                for v in benign:
                    lines.append(_fmt_viol(v))
            if warns:
                lines.append("  ── warning ──")
                for v in warns:
                    lines.append(_fmt_viol(v))
        if n_err == 0:
            return "\n".join(lines)
        # blocking 非空：已修过的部分不再重复，输出当前阻塞项
        return "\n".join(lines)

    # 循环结束仍未过
    return "\n".join(lines + ["❌ 达到最大修复轮数，仍有 blocking 违规，未通过门禁"])


ALL_TOOLS = [
    kicad_sch_erc_gate,
]
