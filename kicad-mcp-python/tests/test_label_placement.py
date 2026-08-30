from __future__ import annotations

import pytest

from kicad_mcp.tools.geometry import Box, GeometryModel
from kicad_mcp.tools.label_placement import solve_label_candidate


def test_label_solver_uses_alternative_direction() -> None:
    candidate = solve_label_candidate(
        "ROW10",
        (10, 10),
        [Box(10, 8, 25, 12)],
        preferred_spin="right",
        page_box=Box(0, 0, 50, 50),
    )

    assert candidate.spin != "right"
    box = GeometryModel.label_box(
        "ROW10", candidate.x_mm, candidate.y_mm, 1.27, candidate.spin
    )
    assert not box.overlaps(Box(10, 8, 25, 12), 1.27)


def test_label_solver_fails_in_fully_blocked_area() -> None:
    with pytest.raises(RuntimeError, match="无满足 1.27mm 净距"):
        solve_label_candidate(
            "NET",
            (10, 10),
            [Box(0, 0, 20, 20)],
            page_box=Box(0, 0, 20, 20),
        )


def test_label_solver_penalizes_crossing_existing_wire() -> None:
    candidate = solve_label_candidate(
        "NET",
        (10, 10),
        [],
        preferred_spin="right",
        wires=[((11, 5), (11, 15))],
        page_box=Box(0, 0, 30, 30),
    )

    assert candidate.spin != "right"