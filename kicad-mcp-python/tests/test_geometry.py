from __future__ import annotations

import pytest

from kicad_mcp.tools.geometry import Box, GeometryModel
from kicad_mcp.tools.overlaps import _check


@pytest.mark.parametrize(
    ("spin", "axis", "direction"),
    [
        ("left", "right", 1),
        ("right", "left", -1),
        ("up", "top", -1),
        ("down", "bottom", 1),
    ],
)
def test_label_box_extends_in_spin_direction(
    spin: str, axis: str, direction: int
) -> None:
    box = GeometryModel.label_box("ROW10", 10, 10, 1.27, spin, "global")

    assert (getattr(box, axis) - 10) * direction > 1.27


def test_clearance_distinguishes_touching_from_required_gap() -> None:
    first = Box(0, 0, 2, 2)
    second = Box(3, 0, 5, 2)
    model = GeometryModel(label_label_clearance_mm=1.27)

    assert first.clearance_to(second) == pytest.approx(1.0)
    assert not first.overlaps(second)
    assert model.violation(first, second, "label_label")


def test_segment_box_supports_wire_clearance() -> None:
    wire = GeometryModel.segment_box((0, 5), (10, 5), width_mm=0.2)
    symbol = Box(4, 6, 6, 8)

    assert wire.clearance_to(symbol) == pytest.approx(0.9)
    assert GeometryModel().violation(wire, symbol, "wire_symbol")


def test_wire_clearance_ignores_owner_and_reports_foreign_symbol() -> None:
    symbols = [
        {"ref": "R1", "bbox": (-1, -1, 1, 1), "pins": [(0, 0)]},
        {"ref": "U1", "bbox": (4, 1, 6, 3), "pins": [(4, 2)]},
    ]

    result = _check(
        symbols, [], [((0, 0), (10, 0), "wire-1")], 100, 100, 0, 1.27
    )

    assert result["wire_sym"] == [("wire-1", "U1")]