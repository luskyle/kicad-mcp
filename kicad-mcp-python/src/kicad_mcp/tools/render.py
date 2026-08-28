"""L0 可视化反馈：把原理图/PCB 渲染成 SVG/PNG，让 AI 能"看见"绘制结果。

这是做图能力提升方案（docs/drawing-improvement-plan.md）的 L0 层。
核心思路：MCP 是纯文本，AI 画完看不到图只能盲猜。SVG 是文本格式，
LLM 可以直接读取其中的坐标/连线/文字来验证绘制是否正确；PNG 3D 图
则给人看。工作流：画 → render 看 → 修正 → 再 render。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from ..client import DOCTYPE_PCB, DOCTYPE_SCHEMATIC, find_document_socket

# SVG 文本默认内联上限：超过则只返回文件路径（避免 MCP 结果过大撑爆上下文）。
DEFAULT_MAX_SVG_CHARS = 300_000

# PCB SVG 默认绘制的层（英文层名，逗号分隔）
DEFAULT_PCB_LAYERS = "F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask"


def _cli_env() -> dict:
    """kicad-cli 运行环境：隔离 conda + 指向资源目录（与 kicad_sch_erc 一致）。"""
    env = dict(os.environ)
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    for k in ("CONDA_PREFIX", "CONDA_DEFAULT_ENV", "PYTHONHOME", "PYTHONPATH"):
        env.pop(k, None)
    env.setdefault("KICAD_STOCK_DATA_HOME", "/tmp/squashfs-root/share/kicad")
    return env


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


def _current_doc_path(doc_type: int) -> str:
    """从当前打开的文档推断 .kicad_sch / .kicad_pcb 的完整路径。"""
    url, docs = find_document_socket(doc_type)
    if url is None:
        kind = "原理图(eeschema)" if doc_type == DOCTYPE_SCHEMATIC else "PCB(pcbnew)"
        raise RuntimeError(f"没有可用的{kind}进程，请先打开对应文档后再渲染")
    doc = docs[0]
    fname = doc.board_filename or ""
    proj = doc.project.path if doc.project and doc.project.path else ""
    if proj:
        return str(Path(proj) / fname)
    return fname


def _run_cli(args: list, timeout: int = 240):
    """运行 kicad-cli 命令，返回 subprocess.CompletedProcess。"""
    return subprocess.run(args, capture_output=True, text=True,
                          env=_cli_env(), timeout=timeout)


def _format_error(proc) -> str:
    return (proc.stderr or proc.stdout or "").strip()[:400]


def _inline_svg(lines: list, svg_path: Path, include_svg: bool,
                max_svg_chars: int) -> None:
    """按大小决定是否把 SVG 文本内联到返回结果。"""
    size = svg_path.stat().st_size
    lines.append(f"   文件: {svg_path}（{size // 1024}KB）")
    if include_svg and size <= max_svg_chars:
        lines.append("──── SVG 内容（AI 可直接读取坐标/连线/文字验证绘制）────")
        lines.append(svg_path.read_text(errors="replace"))
        lines.append("──── SVG 结束 ────")
    elif include_svg:
        lines.append(
            f"   ⚠️ SVG 文本 {size // 1024}KB 超过 {max_svg_chars} 字符，未内联；"
            f"请打开文件查看，或把图纸画小后重试。"
        )


def kicad_sch_render(
    sch_file: Optional[str] = None,
    out: Optional[str] = None,
    include_svg: bool = True,
    max_svg_chars: int = DEFAULT_MAX_SVG_CHARS,
    theme: str = "",
    black_and_white: bool = False,
    draw_hop_over: bool = True,
    no_background: bool = True,
) -> str:
    """把原理图导出为 SVG —— 可视化反馈，让 AI/用户看到绘制结果。

    画完图后调用本工具查看效果。SVG 是文本格式，AI 可直接读取其中的
    坐标、连线、文字、符号来验证绘制是否正确（例如引脚是否连上、元件
    是否重叠、是否出界）。同时 SVG 文件落盘，用户可在浏览器打开。

    Args:
        sch_file: 原理图 .kicad_sch 路径；不传则使用当前 eeschema 打开的文档。
                  （建议先调用 kicad_save_document 保存，再渲染。）
        out: 输出 SVG 文件路径（不传则写到 /tmp 临时目录）。
        include_svg: 是否在结果里内联 SVG 文本（默认 True，供 AI 读取）。
        max_svg_chars: SVG 文本超过该字符数就不再内联（避免结果过大），
            只返回文件路径。
        theme: 配色主题名（如 "KiCad Classic"；默认用原理图自身设置）。
        black_and_white: 黑白输出（默认 False）。
        draw_hop_over: 导线交叉处画跳线弧（默认 True，便于读图）。
        no_background: 不设背景色（默认 True，SVG 更小更干净）。

    Returns:
        渲染文件路径；若尺寸允许，附带 SVG 文本供 AI 读取。
    """
    sch = sch_file or _current_doc_path(DOCTYPE_SCHEMATIC)
    if not os.path.exists(sch):
        raise RuntimeError(f"原理图文件不存在: {sch}")

    # 注意：本版本 kicad-cli 把 -o 当作「目录」，实际生成 <目录>/<sheet名>.svg
    out_dir = Path(out) if out else Path(tempfile.mkdtemp(prefix="kicad_render_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    args = [_find_kicad_cli(), "sch", "export", "svg", "-o", str(out_dir)]
    if theme:
        args += ["--theme", theme]
    if black_and_white:
        args.append("--black-and-white")
    if draw_hop_over:
        args.append("--draw-hop-over")
    if no_background:
        args.append("--no-background-color")
    args.append(sch)

    proc = _run_cli(args, timeout=180)

    # 找出生成的 SVG（优先与原理图同名的页面）
    svg_files = sorted(Path(out_dir).glob("*.svg")) if Path(out_dir).is_dir() else []
    if not svg_files:
        raise RuntimeError(
            f"渲染失败 (exit {proc.returncode}): {_format_error(proc)}")
    stem = Path(sch).stem
    chosen = next((f for f in svg_files if f.stem == stem), svg_files[0])

    lines = [f"✅ 已渲染原理图（{len(svg_files)} 页）"]
    _inline_svg(lines, chosen, include_svg, max_svg_chars)
    return "\n".join(lines)


def kicad_pcb_render(
    pcb_file: Optional[str] = None,
    out: Optional[str] = None,
    format: str = "svg",
    layers: str = DEFAULT_PCB_LAYERS,
    include_svg: bool = True,
    max_svg_chars: int = DEFAULT_MAX_SVG_CHARS,
) -> str:
    """把 PCB 渲染成 SVG（AI 可读 2D 矢量图）或 PNG（3D 渲染图给人看）。

    Args:
        pcb_file: PCB .kicad_pcb 路径；不传则使用当前 pcbnew 打开的文档。
                  （建议先调用 kicad_save_document 保存，再渲染。）
        out: 输出文件路径（不传则写到 /tmp 临时目录）。
        format: "svg"（2D 分层矢量图，AI 可读文本）| "png"（3D 渲染图，适合人看）。
        layers: format=svg 时绘制的层，逗号分隔的英文层名（默认
                "F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask"）。
        include_svg: format=svg 时是否内联 SVG 文本（默认 True）。
        max_svg_chars: SVG 文本超过该字符数不再内联。

    Returns:
        渲染文件路径；format=svg 且尺寸允许时附带 SVG 文本。
    """
    fmt = format.lower()
    if fmt not in ("svg", "png"):
        raise ValueError(f"format 可选 svg / png，收到 {format}")

    pcb = pcb_file or _current_doc_path(DOCTYPE_PCB)
    if not os.path.exists(pcb):
        raise RuntimeError(f"PCB 文件不存在: {pcb}")

    tmp_dir = tempfile.mkdtemp(prefix="kicad_render_")
    if fmt == "svg":
        out_path = out or str(Path(tmp_dir) / "board.svg")
        # --mode-single: 输出单文件（否则 -o 被当目录多文件）
        args = [_find_kicad_cli(), "pcb", "export", "svg", "--mode-single",
                "-l", layers, "-o", out_path, pcb]
    else:
        out_path = out or str(Path(tmp_dir) / "board.png")
        args = [_find_kicad_cli(), "pcb", "render", "-o", out_path, pcb]

    proc = _run_cli(args, timeout=240)
    if not os.path.exists(out_path):
        raise RuntimeError(
            f"渲染失败 (exit {proc.returncode}): {_format_error(proc)}")

    size = os.path.getsize(out_path)
    lines = [f"✅ 已渲染 PCB ({fmt})"]
    if fmt == "svg":
        _inline_svg(lines, Path(out_path), include_svg, max_svg_chars)
    else:
        lines.append(f"   文件: {out_path}（{size // 1024}KB）")
        lines.append("   PNG 是 3D 渲染图（供人查看，AI 无法直接读图）。"
                     "如需 AI 检查布局请用 format=\"svg\"。")
    return "\n".join(lines)


ALL_TOOLS = [
    kicad_sch_render,
    kicad_pcb_render,
]
