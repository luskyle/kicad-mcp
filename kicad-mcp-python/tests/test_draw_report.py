from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from kicad_mcp.tools import draw_report
from kicad_mcp.tools.draw_report import DrawReport, kicad_sch_quality_pipeline


def test_draw_report_serializes_gate_metrics(tmp_path: Path) -> None:
    report = DrawReport("demo.kicad_sch")
    report.add_gate("schema", "passed", time.monotonic(), metrics={"issues": 0})
    report.status = "passed"

    path = report.write(tmp_path / "draw-report.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["status"] == "passed"
    assert payload["gates"][0]["metrics"] == {"issues": 0}


def test_quality_pipeline_runs_all_gates_and_writes_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schematic = tmp_path / "demo.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")
    artifacts = tmp_path / "quality"
    snapshot = {"sheets": [{"file": "demo.kicad_sch"}], "connections": []}
    monkeypatch.setattr(draw_report, "ensure_kicad_project", lambda path: "project ok")
    monkeypatch.setattr(draw_report, "validate_schematic_hierarchy", lambda path: [])
    monkeypatch.setattr(draw_report, "semantic_snapshot", lambda path: snapshot)
    monkeypatch.setattr(draw_report, "_erc_violations", lambda path: [])
    monkeypatch.setattr(
        draw_report, "kicad_sch_check_overlaps", lambda **kwargs: "✅ 无重叠/越界"
    )
    monkeypatch.setattr(draw_report, "kicad_sch_reload_gate", lambda **kwargs: "reload ok")

    def render(**kwargs) -> str:
        svg_dir = Path(kwargs["out"])
        svg_dir.mkdir(parents=True, exist_ok=True)
        (svg_dir / "demo.svg").write_text("<svg><path/></svg>", encoding="utf-8")
        return "render ok"

    monkeypatch.setattr(draw_report, "kicad_sch_render", render)

    result = kicad_sch_quality_pipeline(
        str(schematic), str(artifacts), reload_rounds=1
    )
    payload = json.loads((artifacts / "draw-report.json").read_text(encoding="utf-8"))

    assert "7 gates" in result
    assert payload["status"] == "passed"
    assert [gate["name"] for gate in payload["gates"]] == [
        "schema", "topology", "erc", "geometry", "reload", "visual", "golden"
    ]
    assert (artifacts / "semantic-snapshot.json").exists()

    second = kicad_sch_quality_pipeline(
        str(schematic), str(artifacts), reload_rounds=1
    )
    second_payload = json.loads(
        (artifacts / "draw-report.json").read_text(encoding="utf-8")
    )
    assert "7 gates" in second
    assert second_payload["gates"][-1]["message"] == "连接图与 Golden 一致"


def test_quality_pipeline_persists_failed_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schematic = tmp_path / "bad.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")
    artifacts = tmp_path / "quality"
    monkeypatch.setattr(
        draw_report, "ensure_kicad_project", lambda path: (_ for _ in ()).throw(
            RuntimeError("missing child")
        )
    )

    with pytest.raises(RuntimeError, match="schema gate 失败"):
        kicad_sch_quality_pipeline(str(schematic), str(artifacts))

    payload = json.loads((artifacts / "draw-report.json").read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["gates"][0]["name"] == "schema"