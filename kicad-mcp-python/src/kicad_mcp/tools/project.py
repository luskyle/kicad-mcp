"""KiCad project scaffolding and local library validation."""

from __future__ import annotations

import json
import os
import re
import tempfile
from importlib import resources
from pathlib import Path
from typing import Optional

from ..symbols import parse_sexpr


_LIB_TABLES = {
    "sym-lib-table": "sym_lib_table",
    "fp-lib-table": "fp_lib_table",
}


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _create_project_file(project_file: Path) -> None:
    template = resources.files("kicad_mcp").joinpath(
        "resources", "kicad.kicad_pro"
    )
    data = json.loads(template.read_text(encoding="utf-8"))
    data["meta"]["filename"] = project_file.name
    _write_atomic(project_file, json.dumps(data, indent=2) + "\n")


def _ensure_library_tables(project_dir: Path) -> list[Path]:
    created = []
    for filename, root_name in _LIB_TABLES.items():
        path = project_dir / filename
        if not path.exists():
            _write_atomic(path, f"({root_name}\n  (version 7)\n)\n")
            created.append(path)
    return created


def _missing_project_resources(schematic: Path) -> list[str]:
    project_dir = schematic.parent
    missing = []
    uri_pattern = re.compile(r'\(uri\s+"([^"]+)"\)')
    for filename in _LIB_TABLES:
        table = project_dir / filename
        text = table.read_text(encoding="utf-8")
        for uri in uri_pattern.findall(text):
            if "${KIPRJMOD}" not in uri:
                continue
            expanded = uri.replace("${KIPRJMOD}", str(project_dir))
            path = Path(expanded)
            if not path.exists():
                missing.append(f"{filename}: {uri}")

    local_path_pattern = re.compile(r'"(\$\{KIPRJMOD\}/[^"]+)"')
    schematic_text = schematic.read_text(encoding="utf-8")
    for value in sorted(set(local_path_pattern.findall(schematic_text))):
        expanded = value.replace("${KIPRJMOD}", str(project_dir))
        if not Path(expanded).exists():
            missing.append(f"{schematic.name}: {value}")
    return missing


def _child(node: list, tag: str) -> list | None:
    return next(
        (item for item in node if isinstance(item, list) and item[:1] == [tag]),
        None,
    )


def _atom(node: list, tag: str) -> str:
    child = _child(node, tag)
    return str(child[1]) if child and len(child) > 1 else ""


def _nodes(node, tag: str):
    if isinstance(node, list):
        if node[:1] == [tag]:
            yield node
        for child in node:
            yield from _nodes(child, tag)


def _schematic_root(path: Path) -> list:
    parsed = parse_sexpr(path.read_text(encoding="utf-8"))
    if len(parsed) != 1 or parsed[0][:1] != ["kicad_sch"]:
        raise RuntimeError(f"无效的 KiCad 原理图: {path}")
    return parsed[0]


def validate_schematic_hierarchy(schematic: str | Path) -> list[str]:
    """Return structural errors that would trigger repairs during GUI load."""
    root_path = Path(schematic).resolve()
    project_name = root_path.stem
    root = _schematic_root(root_path)
    root_uuid = _atom(root, "uuid")
    direct_sheets = [
        node for node in root[1:]
        if isinstance(node, list) and node[:1] == ["sheet"]
    ]
    if not direct_sheets:
        return []
    if not root_uuid:
        return [f"{root_path.name}: 层级根页缺少顶层 UUID"]

    issues = []
    seen_uuids: dict[str, Path] = {}
    pending = [(root_path, root, f"/{root_uuid}")]
    visited: set[Path] = set()
    declared_pages: set[str] = set()

    while pending:
        path, current, hierarchy_path = pending.pop(0)
        if path in visited:
            continue
        visited.add(path)
        file_uuid = _atom(current, "uuid")
        if not file_uuid:
            issues.append(f"{path.name}: 缺少顶层 UUID")
        elif file_uuid in seen_uuids:
            issues.append(
                f"{path.name}: 顶层 UUID 与 {seen_uuids[file_uuid].name} 重复: {file_uuid}"
            )
        else:
            seen_uuids[file_uuid] = path

        sheet_instances = _child(current, "sheet_instances")
        root_instance = _child(sheet_instances, "path") if sheet_instances else None
        actual_page = _atom(root_instance, "page") if root_instance else ""
        if path == root_path and actual_page and actual_page != "1":
            issues.append(
                f"{path.name}: 根页 sheet_instances 页码为 {actual_page}，应为 1"
            )

        if path != root_path:
            for symbol in _nodes(current, "symbol"):
                instances = _child(symbol, "instances")
                if not instances:
                    continue
                for project in (
                    item for item in instances
                    if isinstance(item, list) and item[:2] == ["project", project_name]
                ):
                    instance_path = _child(project, "path")
                    if instance_path and str(instance_path[1]) != hierarchy_path:
                        issues.append(
                            f"{path.name}: symbol 实例路径 {instance_path[1]}，"
                            f"应为 {hierarchy_path}"
                        )
                        break

        for sheet in (
            node for node in current[1:]
            if isinstance(node, list) and node[:1] == ["sheet"]
        ):
            sheet_uuid = _atom(sheet, "uuid")
            sheet_file = ""
            for prop in (
                item for item in sheet
                if isinstance(item, list) and item[:1] == ["property"]
            ):
                if len(prop) > 2 and prop[1] == "Sheetfile":
                    sheet_file = str(prop[2])
                    break
            if not sheet_uuid or not sheet_file:
                issues.append(f"{path.name}: Sheet 缺少 UUID 或 Sheetfile")
                continue

            declared_page = ""
            instances = _child(sheet, "instances")
            for project in instances or []:
                if isinstance(project, list) and project[:2] == ["project", project_name]:
                    instance_path = _child(project, "path")
                    if instance_path:
                        if str(instance_path[1]) != hierarchy_path:
                            issues.append(
                                f"{path.name}: Sheet 父路径 {instance_path[1]}，"
                                f"应为 {hierarchy_path}"
                            )
                        declared_page = _atom(instance_path, "page")

            if not declared_page:
                issues.append(f"{path.name}: Sheet {sheet_file} 缺少项目页码")
            elif declared_page in declared_pages:
                issues.append(f"{path.name}: 层级页码重复: {declared_page}")
            else:
                declared_pages.add(declared_page)

            child_path = (path.parent / sheet_file).resolve()
            if not child_path.is_file():
                issues.append(f"{path.name}: 子页不存在: {sheet_file}")
                continue
            child_root = _schematic_root(child_path)
            pending.append(
                (child_path, child_root, f"{hierarchy_path}/{sheet_uuid}")
            )

    return issues


def ensure_kicad_project(sch_file: str, strict: bool = True) -> str:
    """Ensure that a schematic belongs to a complete local KiCad project.

    Missing project and library-table files are created from KiCad's project
    template. Existing files are never overwritten. Project-local library URIs
    are validated before drawing starts.
    """
    schematic = Path(sch_file).expanduser().resolve()
    if schematic.suffix.lower() != ".kicad_sch":
        raise ValueError(f"不是 KiCad 原理图文件: {schematic}")

    project_file = schematic.with_suffix(".kicad_pro")
    created = []
    if not project_file.exists():
        _create_project_file(project_file)
        created.append(project_file)
    created.extend(_ensure_library_tables(schematic.parent))

    missing = _missing_project_resources(schematic)
    hierarchy_issues = validate_schematic_hierarchy(schematic)
    if missing and strict:
        details = "\n".join(f"  - {item}" for item in missing)
        raise RuntimeError(f"项目本地库路径不存在:\n{details}")
    if hierarchy_issues and strict:
        details = "\n".join(f"  - {item}" for item in hierarchy_issues)
        raise RuntimeError(f"原理图层级结构无效:\n{details}")

    lines = [f"KiCad 工程预检通过: {project_file}"]
    if created:
        lines.append("已创建: " + ", ".join(path.name for path in created))
    if missing:
        lines.append("缺失本地库: " + ", ".join(missing))
    if hierarchy_issues:
        lines.append("层级结构问题: " + ", ".join(hierarchy_issues))
    return "\n".join(lines)


def kicad_sch_ensure_project(
    sch_file: Optional[str] = None,
    strict: bool = True,
) -> str:
    """Create and validate project files for a KiCad schematic.

    Args:
        sch_file: Schematic path. Uses the currently open schematic when empty.
        strict: Fail when a `${KIPRJMOD}` library path does not exist.
    """
    if not sch_file:
        from .schematic import _current_sch_path

        sch_file = _current_sch_path()
    return ensure_kicad_project(sch_file, strict=strict)


ALL_TOOLS = [kicad_sch_ensure_project]