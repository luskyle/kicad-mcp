"""符号库浏览器：列出/搜索 KiCad 系统符号库，供 AI 自由放置任意符号。

工具：
- kicad_sch_list_libraries: 列出所有可用符号库（系统 + 项目私有）
- kicad_sch_search_symbols: 按关键字搜索符号
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..runtime import resolve_kicad_runtime


def _parse_lib_table() -> list[dict]:
    """解析 sym-lib-table，返回 [{name, uri, descr}]。"""
    libs = []
    table = resolve_kicad_runtime().symbol_lib_table
    if not table.exists():
        return libs
    text = table.read_text(encoding="utf-8")
    for m in re.finditer(
            r'\(lib\s+\(name\s+"([^"]+)"\)\s+\(type\s+"([^"]+)"\)\s+\(uri\s+"([^"]+)"\)'
            r'(?:\s+\(options\s+"[^"]*"\))?(?:\s+\(descr\s+"([^"]*)"\))?',
            text):
        libs.append({"name": m.group(1), "type": m.group(2),
                     "uri": m.group(3), "descr": m.group(4) or ""})
    return libs


def _symbol_files(lib_dir: Path) -> list[str]:
    """列出 .kicad_symdir 目录下的符号名，或单文件 .kicad_sym 的符号。"""
    names = []
    if lib_dir.is_dir():
        for f in sorted(lib_dir.glob("*.kicad_sym")):
            names.append(f.stem)
    elif lib_dir.is_file():
        names.append(lib_dir.stem)
    return names


def kicad_sch_list_libraries() -> str:
    """列出所有可用的符号库（系统库 + 项目私有库）及符号数量。

    Returns:
        每个库一行: 库名 (类型) 路径 [符号数]
    """
    lines = []
    libs = _parse_lib_table()
    if not libs:
        return "sym-lib-table 为空或不存在"

    for lib in libs:
        uri = Path(lib["uri"])
        n = len(_symbol_files(uri))
        lines.append(f"  {lib['name']:<20} {lib['type']:<10} {n:>3} 个符号  {uri}")
    lines.insert(0, f"共 {len(libs)} 个库:")
    return "\n".join(lines)


def kicad_sch_search_symbols(query: str, library: str = "",
                             max_results: int = 40) -> str:
    """在符号库中按名称搜索符号。

    Args:
        query: 搜索关键字（子串匹配，不区分大小写），如 "LM358"、"NRF"。
        library: 可选，限定搜索的库名（如 "Device"、"MCU_ST_STM32"）；
            不传则搜索所有已挂载库 + 系统库目录。
        max_results: 最多返回条数。

    Returns:
        匹配的符号列表（库名:符号名）。
    """
    query = query.strip().lower()
    if not query:
        return "请提供搜索关键字（query）"

    matches = []
    libs = _parse_lib_table()
    searched = set()

    # 先搜已挂载库
    for lib in libs:
        if library and lib["name"].lower() != library.lower():
            continue
        uri = Path(lib["uri"])
        for name in _symbol_files(uri):
            if query in name.lower():
                matches.append(f"{lib['name']}:{name}")
        searched.add(uri)

    # 再搜系统符号目录中未挂载的库（保证所有系统符号可被调用）
    system_symbol_dir = resolve_kicad_runtime().symbol_dir
    if not library and system_symbol_dir.is_dir():
        for d in sorted(system_symbol_dir.glob("*.kicad_symdir")):
            if d in searched:
                continue
            for name in _symbol_files(d):
                if query in name.lower():
                    matches.append(f"{d.name.replace('.kicad_symdir','')}:{name}")

    if not matches:
        return f"未找到包含 '{query}' 的符号"
    if len(matches) > max_results:
        head = matches[:max_results]
        return f"找到 {len(matches)} 个（显示前 {max_results}）:\n" + "\n".join(f"  {m}" for m in head)
    return f"找到 {len(matches)} 个:\n" + "\n".join(f"  {m}" for m in matches)


ALL_TOOLS = [
    kicad_sch_list_libraries,
    kicad_sch_search_symbols,
]
