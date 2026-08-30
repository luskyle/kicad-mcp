"""Structured V2.6 drawing report and one-command quality pipeline."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .overlaps import kicad_sch_check_overlaps
from .project import ensure_kicad_project, validate_schematic_hierarchy
from .quality import _classify, _erc_violations
from .reload import kicad_sch_reload_gate, semantic_snapshot
from .render import kicad_sch_render
from .schematic import _current_sch_path
from .svg_metrics import analyze_svg


@dataclass
class GateResult:
    name: str
    status: str
    duration_ms: int
    message: str = ""
    metrics: dict = field(default_factory=dict)


@dataclass
class DrawReport:
    schematic: str
    status: str = "running"
    schema_version: int = 1
    gates: list[GateResult] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)

    def add_gate(
        self,
        name: str,
        status: str,
        started: float,
        message: str = "",
        metrics: Optional[dict] = None,
    ) -> None:
        self.gates.append(GateResult(
            name=name,
            status=status,
            duration_ms=round((time.monotonic() - started) * 1000),
            message=message,
            metrics=metrics or {},
        ))

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
        return target


def _run_gate(
    report: DrawReport,
    report_path: Path,
    name: str,
    operation: Callable[[], tuple[str, dict]],
) -> tuple[str, dict]:
    started = time.monotonic()
    try:
        message, metrics = operation()
    except Exception as exc:
        report.status = "failed"
        report.add_gate(name, "failed", started, str(exc))
        report.write(report_path)
        raise RuntimeError(f"{name} gate 失败: {exc}；报告: {report_path}") from exc
    report.add_gate(name, "passed", started, message, metrics)
    report.write(report_path)
    return message, metrics


def kicad_sch_quality_pipeline(
    sch_file: Optional[str] = None,
    output_dir: Optional[str] = None,
    reload_rounds: int = 2,
    clearance_mm: float = 1.27,
) -> str:
    """Run all V2.6 schematic gates and emit stable machine-readable artifacts."""
    schematic = Path(sch_file or _current_sch_path()).resolve()
    artifacts = Path(output_dir).resolve() if output_dir else schematic.with_suffix(".quality")
    artifacts.mkdir(parents=True, exist_ok=True)
    report_path = artifacts / "draw-report.json"
    report = DrawReport(str(schematic))
    report.artifacts["report"] = str(report_path)
    report.write(report_path)

    def schema_gate() -> tuple[str, dict]:
        message = ensure_kicad_project(str(schematic))
        issues = validate_schematic_hierarchy(schematic)
        if issues:
            raise RuntimeError("; ".join(issues))
        return message, {"hierarchy_issues": 0}

    _run_gate(report, report_path, "schema", schema_gate)

    snapshot: dict = {}

    def topology_gate() -> tuple[str, dict]:
        nonlocal snapshot
        snapshot = semantic_snapshot(schematic)
        sheet_count = len(snapshot["sheets"])
        connection_count = len(snapshot["connections"])
        if sheet_count < 1:
            raise RuntimeError("语义快照不包含原理图页")
        return "层级与连接图可解析", {
            "sheets": sheet_count,
            "connections": connection_count,
        }

    _run_gate(report, report_path, "topology", topology_gate)

    def erc_gate() -> tuple[str, dict]:
        violations = _erc_violations(str(schematic))
        blocking, benign, warnings = _classify(violations)
        if blocking:
            raise RuntimeError(f"存在 {len(blocking)} 条 blocking ERC 违规")
        return "ERC blocking 为 0", {
            "blocking": 0,
            "benign": len(benign),
            "warnings": len(warnings),
        }

    _run_gate(report, report_path, "erc", erc_gate)

    def geometry_gate() -> tuple[str, dict]:
        message = kicad_sch_check_overlaps(
            clearance_mm=clearance_mm, sch_file=str(schematic)
        )
        if "❌" in message:
            raise RuntimeError(message.splitlines()[0])
        return message.splitlines()[0], {"clearance_mm": clearance_mm}

    _run_gate(report, report_path, "geometry", geometry_gate)

    def reload_gate() -> tuple[str, dict]:
        message = kicad_sch_reload_gate(rounds=reload_rounds)
        return message, {"rounds": reload_rounds}

    _run_gate(report, report_path, "reload", reload_gate)

    def visual_gate() -> tuple[str, dict]:
        message = kicad_sch_render(
            sch_file=str(schematic), out=str(artifacts / "svg"), include_svg=False
        )
        svg_files = sorted((artifacts / "svg").glob("*.svg"))
        empty = [path.name for path in svg_files if path.stat().st_size == 0]
        if not svg_files or empty:
            raise RuntimeError(f"SVG 产物缺失或为空: {empty}")
        measurements = [analyze_svg(path) for path in svg_files]
        if any(not item["inside_page"] for item in measurements):
            raise RuntimeError("SVG 绘图元素超出页面 viewBox")
        report.artifacts["svg_dir"] = str(artifacts / "svg")
        return message.splitlines()[0], {
            "files": len(svg_files),
            "bytes": sum(path.stat().st_size for path in svg_files),
            "drawable_elements": sum(item["drawable_elements"] for item in measurements),
            "measurements": measurements,
        }

    _run_gate(report, report_path, "visual", visual_gate)

    golden_path = artifacts / "semantic-snapshot.json"
    normalized_snapshot = json.loads(json.dumps(snapshot, ensure_ascii=False))
    if golden_path.exists():
        expected = json.loads(golden_path.read_text(encoding="utf-8"))
        if expected != normalized_snapshot:
            report.status = "failed"
            report.add_gate("golden", "failed", time.monotonic(), "连接图偏离 Golden")
            report.write(report_path)
            raise RuntimeError(f"golden gate 失败: 连接图偏离基线；报告: {report_path}")
        report.add_gate("golden", "passed", time.monotonic(), "连接图与 Golden 一致")
    else:
        golden_path.write_text(
            json.dumps(normalized_snapshot, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report.add_gate("golden", "passed", time.monotonic(), "已建立 Golden 基线")
    report.artifacts["golden"] = str(golden_path)
    report.status = "passed"
    report.write(report_path)
    return f"V2.6 全门禁通过（{len(report.gates)} gates）；报告: {report_path}"


ALL_TOOLS = [kicad_sch_quality_pipeline]