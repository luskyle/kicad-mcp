"""L4 prompt 模板库：预置"画 XX 电路"的分步指令模板，降低 LLM 编排成本。

模板存于 kicad-mcp-python/prompts/*.md，LLM 在编排前用
`kicad_get_prompt_template` 取一份"分步指令"照着做：
  - 画通用电路   → draw-circuit
  - 画电源电路   → draw-power
  - 画 MCU 主控页 → draw-mcu
  - 画键盘矩阵   → draw-matrix
  - 验证/仿真     → verify-simulate
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"

_DEFAULT = "draw-circuit"

_TITLES = {
    "draw-circuit": "画一个 XX 电路（通用）",
    "draw-power": "画电源电路（USBC/LDO/去耦）",
    "draw-mcu": "画 MCU 主控页（大芯片）",
    "draw-matrix": "画键盘矩阵",
    "verify-simulate": "验证 / 仿真电路",
}


def _read_template(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"没有模板 {name!r}。可用: {', '.join(sorted(_TITLES))}（文件在 {PROMPTS_DIR}）")
    return path.read_text(encoding="utf-8")


def kicad_list_prompt_templates() -> str:
    """列出所有预置的画图/验证模板（L4 prompt 模板库）。"""
    lines = ["📚 可用 prompt 模板："]
    for name, title in sorted(_TITLES.items()):
        lines.append(f"  · {name:16s} — {title}")
    lines.append("取用: kicad_get_prompt_template(name=...)")
    return "\n".join(lines)


def kicad_get_prompt_template(name: str = _DEFAULT) -> str:
    """返回一个"画 XX 电路"的分步指令模板，照做即可少踩坑。

    Args:
        name: 模板名，可选 draw-circuit / draw-power / draw-mcu /
              draw-matrix / verify-simulate。

    Returns:
        模板 markdown 文本（步骤、circuit_json 例子、约定、检查清单）。
    """
    name = name.strip().lower()
    if name not in _TITLES:
        raise ValueError(
            f"未知模板 {name!r}。可用: {', '.join(sorted(_TITLES))}")
    return _read_template(name)


ALL_TOOLS = [
    kicad_get_prompt_template,
    kicad_list_prompt_templates,
]
