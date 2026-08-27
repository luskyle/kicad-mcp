"""自定义符号库工具：把规格书（引脚/属性）转换为 KiCad 符号并加入项目私有库。

MCP 工具：
- kicad_sch_create_custom_symbol: 规格书 -> .kicad_sym 符号 -> 项目私有库
  （sym-lib-table 挂载；重启 eeschema 后可用 kicad_sch_add_symbol 放置）

私有库约定：每个项目一个库，库名 `<项目名>_local`，文件在项目目录下。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from ..symbol_writer import parse_spec, build_symbol, write_lib_file, write_symdir
from ..client import DOCTYPE_SCHEMATIC, KiCadClient, find_document_socket

KICAD_CONFIG_DIR = Path.home() / ".config/kicad" / "10.0"
SYM_LIB_TABLE = KICAD_CONFIG_DIR / "sym-lib-table"


def _current_sch_path() -> str:
    """从当前打开的 eeschema 文档推断 .kicad_sch 完整路径。"""
    url, docs = find_document_socket(DOCTYPE_SCHEMATIC)
    if url is None:
        raise RuntimeError("没有可用的原理图进程，请先启动 eeschema 并打开一个 .kicad_sch 文件")
    doc = docs[0]
    proj_path = doc.project.path if doc.project and doc.project.path else ""
    if proj_path:
        return str(Path(proj_path) / (doc.board_filename or ""))
    return doc.board_filename or ""


def ensure_lib_table() -> Path:
    """确保 sym-lib-table 存在，返回其路径。"""
    KICAD_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not SYM_LIB_TABLE.exists():
        SYM_LIB_TABLE.write_text("(sym_lib_table\n\t(version 7)\n)\n", encoding="utf-8")
    return SYM_LIB_TABLE


def add_lib_to_table(lib_name: str, uri: str) -> bool:
    """把库条目加入 sym-lib-table。返回是否新增（False 表示已存在）。"""
    table = ensure_lib_table()
    text = table.read_text(encoding="utf-8")
    if re.search(r'\(lib\s+\(name\s+"' + re.escape(lib_name) + r'"\)', text):
        return False
    entry = (f'\t(lib (name "{lib_name}") (type "KiCad") (uri "{uri}") '
             f'(options "") (descr "Custom local symbol library"))')
    # 插到 sym_lib_table 的闭合括号前
    if text.strip().endswith(")"):
        idx = text.rstrip().rfind(")")
        text = text[:idx] + entry + "\n" + text[idx:]
    else:
        text = text.rstrip() + "\n" + entry + "\n"
    table.write_text(text, encoding="utf-8")
    return True


def kicad_sch_create_custom_symbol(
    spec: str,
    lib_name: str = "",
    sch_file: Optional[str] = None,
    overwrite: bool = False,
) -> str:
    """根据元件规格书创建自定义 KiCad 符号并加入项目私有库。

    从规格书（JSON 或文本表格）提取引脚（编号/名称/电气类型）和属性，自动生成
    KiCad 符号（引脚左右/上下布局、符号框自动尺寸），写入项目的私有符号库
    （每个项目一个库，默认库名 `<项目名>_local`），并挂载到 sym-lib-table。

    Args:
        spec: 规格书。支持 JSON 或文本：
              JSON: {"name":"ATtiny85","reference":"U","description":"...",
                     "footprint":"DIP-8",
                     "pins":[{"number":"1","name":"RST","type":"input"}, ...]}
              文本: "元件: ATtiny85\\n描述: ...\\n封装: DIP-8\\n引脚:\\n1: RST input\\n2: VCC power_in"
              引脚电气类型: input/output/passive/power_in/power_out/bidirectional/
              tri_state/open_collector/open_emitter/no_connect/unspecified。
        lib_name: 私有库名；默认 `<项目名>_local`（如 rc_charge_local）。
        sch_file: 原理图路径（决定项目目录）；不传则用当前 eeschema 打开的文档。
        overwrite: 覆盖已有的同名符号（默认 False）。

    Returns:
        库名/符号名/引脚清单，以及「重启 eeschema 后即可用 kicad_sch_add_symbol 放置」的提示。
    """
    part = parse_spec(spec)
    if not part["pins"]:
        raise RuntimeError(
            "未能从规格书解析出引脚。请提供引脚列表，例如:\n"
            '1: VCC power_in\\n2: GND power_in\\n3: IN input\\n4: OUT output')

    # 确定项目目录
    sch = sch_file or _current_sch_path()
    project_dir = Path(sch).parent
    project_name = Path(sch).stem

    # 库名：默认 <项目名>_local（小写）
    lib_name = (lib_name or f"{project_name.lower()}_local").lower()
    if not re.match(r"^[A-Za-z0-9_\-]+$", lib_name):
        raise RuntimeError(f"库名不合法: {lib_name}（仅字母/数字/_/-）")

    # 用 .kicad_symdir 目录库（KiCad 10 标准；单文件 .kicad_sym 在本环境 eeschema
    # 加载失败）
    lib_dir = project_dir / f"{lib_name}.kicad_symdir"
    sym_file = lib_dir / f"{part['name']}.kicad_sym"

    # 检查是否已有同名符号
    sym_name = part["name"]
    if sym_file.exists() and not overwrite:
        raise RuntimeError(
            f"库 {lib_dir.name} 中已有符号 {sym_name}（可用 overwrite=True 覆盖）")

    # 写入符号文件（每符号一个文件，追加即新增文件）
    write_symdir([part], str(lib_dir))

    added = add_lib_to_table(lib_name, str(lib_dir))

    # 整理输出
    layout_pin_lines = []
    from ..symbol_writer import layout_pins
    for p in layout_pins(part["pins"])["pins"]:
        layout_pin_lines.append(
            f"    {p['number']:>3} {p['name']:<12} {p['type']:<12} "
            f"({p['side']}, {p['x']:g},{p['y']:g}mm)")

    lines = [
        f"✅ 已创建自定义符号: {lib_name}:{sym_name}",
        f"   库文件: {sym_file}",
        f"   描述: {part.get('description', '') or '-'}",
        f"   封装: {part.get('footprint', '') or '-'}",
        f"   sym-lib-table: {'已新增' if added else '已存在'} 库 '{lib_name}'",
        f"   引脚 ({len(part['pins'])}):",
    ] + layout_pin_lines + [
        "",
        "👉 请重启 eeschema（重新加载符号库）后，用 "
        f"kicad_sch_add_symbol(lib_nickname=\"{lib_name}\", entry_name=\"{sym_name}\", ...) "
        "放置该元件。",
    ]
    return "\n".join(lines)


ALL_TOOLS = [
    kicad_sch_create_custom_symbol,
]
