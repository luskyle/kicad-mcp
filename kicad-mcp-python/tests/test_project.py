from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.tools.project import ensure_kicad_project, validate_schematic_hierarchy


def _hierarchy_root(child_file: str, child_uuid: str = "sheet-uuid") -> str:
        return f'''(kicad_sch
    (uuid "root-uuid")
    (sheet
        (uuid "{child_uuid}")
        (property "Sheetfile" "{child_file}")
        (instances
            (project "root"
                (path "/root-uuid" (page "2")))))
    (sheet_instances (path "/" (page "1"))))
'''


def test_ensure_project_creates_complete_scaffold(tmp_path: Path) -> None:
    schematic = tmp_path / "sample.kicad_sch"
    schematic.write_text("(kicad_sch)\n", encoding="utf-8")

    result = ensure_kicad_project(str(schematic))

    project = tmp_path / "sample.kicad_pro"
    data = json.loads(project.read_text(encoding="utf-8"))
    assert data["meta"]["filename"] == "sample.kicad_pro"
    assert data["meta"]["version"] == 1
    assert (tmp_path / "sym-lib-table").exists()
    assert (tmp_path / "fp-lib-table").exists()
    assert "sample.kicad_pro" in result


def test_ensure_project_never_overwrites_existing_project(tmp_path: Path) -> None:
    schematic = tmp_path / "sample.kicad_sch"
    schematic.write_text("(kicad_sch)\n", encoding="utf-8")
    project = tmp_path / "sample.kicad_pro"
    original = '{"custom": true}\n'
    project.write_text(original, encoding="utf-8")

    ensure_kicad_project(str(schematic))

    assert project.read_text(encoding="utf-8") == original


def test_ensure_project_rejects_missing_project_library(tmp_path: Path) -> None:
    schematic = tmp_path / "sample.kicad_sch"
    schematic.write_text("(kicad_sch)\n", encoding="utf-8")
    (tmp_path / "sym-lib-table").write_text(
        '(sym_lib_table\n  (version 7)\n'
        '  (lib (name "missing") (type "KiCad") '
        '(uri "${KIPRJMOD}/missing.kicad_symdir") (options "") (descr ""))\n)\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="missing.kicad_symdir"):
        ensure_kicad_project(str(schematic))


def test_ensure_project_rejects_missing_schematic_resource(tmp_path: Path) -> None:
    schematic = tmp_path / "sample.kicad_sch"
    schematic.write_text(
        '(kicad_sch (property "Datasheet" "${KIPRJMOD}/missing.pdf"))\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="missing.pdf"):
        ensure_kicad_project(str(schematic))


def test_hierarchy_validation_rejects_missing_child(tmp_path: Path) -> None:
    schematic = tmp_path / "root.kicad_sch"
    schematic.write_text(_hierarchy_root("missing.kicad_sch"), encoding="utf-8")

    assert validate_schematic_hierarchy(schematic) == [
        "root.kicad_sch: 子页不存在: missing.kicad_sch"
    ]


def test_hierarchy_validation_rejects_duplicate_root_uuid(tmp_path: Path) -> None:
    schematic = tmp_path / "root.kicad_sch"
    child = tmp_path / "child.kicad_sch"
    schematic.write_text(_hierarchy_root(child.name), encoding="utf-8")
    child.write_text(
        '(kicad_sch (uuid "root-uuid") '
        '(sheet_instances (path "/" (page "2"))))\n',
        encoding="utf-8",
    )

    issues = validate_schematic_hierarchy(schematic)

    assert issues == [
        "child.kicad_sch: 顶层 UUID 与 root.kicad_sch 重复: root-uuid"
    ]