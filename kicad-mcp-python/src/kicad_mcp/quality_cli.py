"""Command-line entry point for the V2.6 quality pipeline."""

from __future__ import annotations

import argparse

from .tools.draw_report import kicad_sch_quality_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all KiCad MCP schematic quality gates")
    parser.add_argument("schematic")
    parser.add_argument("--output-dir")
    parser.add_argument("--reload-rounds", type=int, default=2)
    parser.add_argument("--clearance-mm", type=float, default=1.27)
    args = parser.parse_args()
    print(kicad_sch_quality_pipeline(
        args.schematic,
        args.output_dir,
        args.reload_rounds,
        args.clearance_mm,
    ))


if __name__ == "__main__":
    main()