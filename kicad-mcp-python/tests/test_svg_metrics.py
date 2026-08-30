from __future__ import annotations

from pathlib import Path

from kicad_mcp.tools.svg_metrics import analyze_svg


def test_svg_metrics_measure_page_ink_and_text_clearance(tmp_path: Path) -> None:
    svg = tmp_path / "drawing.svg"
    svg.write_text(
        '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">
<path d="M 5 5 L 95 5 L 95 45"/>
<text x="10" y="20" font-size="2">ROW0</text>
<text x="20" y="20" font-size="2">ROW1</text>
</svg>''',
        encoding="utf-8",
    )

    metrics = analyze_svg(svg)

    assert metrics["drawable_elements"] == 3
    assert metrics["text_elements"] == 2
    assert metrics["inside_page"]
    assert metrics["ink_bounds"] == [5.0, 5.0, 95.0, 45.0]
    assert metrics["minimum_text_clearance_mm"] is not None