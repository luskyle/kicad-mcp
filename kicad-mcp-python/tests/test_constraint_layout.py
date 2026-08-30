from __future__ import annotations

from kicad_mcp.tools.constraint_layout import apply_constraints


def test_constraints_align_and_expand_dense_column() -> None:
    layout = {"R1": (10, 10, 0), "R2": (12, 10, 0), "R3": (14, 10, 0)}
    sizes = {ref: (5, 5) for ref in layout}

    result, diagnostics = apply_constraints(
        layout,
        sizes,
        {"same_column": [["R1", "R2", "R3"]], "min_spacing_mm": 1.27},
    )

    assert len({position[0] for position in result.values()}) == 1
    assert len({position[1] for position in result.values()}) == 3
    assert diagnostics.expanded_axes > 0
    assert diagnostics.stages == ["topology", "ordering", "sizing", "packing"]


def test_constraints_honor_fixed_position_and_keepout() -> None:
    layout = {"U1": (10, 10, 0), "R1": (20, 10, 0)}
    sizes = {"U1": (5, 5), "R1": (5, 5)}

    result, diagnostics = apply_constraints(
        layout,
        sizes,
        {
            "fixed": {"U1": [5.08, 7.62, 90]},
            "keepouts": [[17, 7, 25, 13]],
            "min_spacing_mm": 1.27,
        },
    )

    assert result["U1"] == (5.08, 7.62, 90)
    assert result["R1"][0] > 25
    assert diagnostics.violations == []


def test_constraints_recommend_pagination_for_out_of_bounds_symbol() -> None:
    result, diagnostics = apply_constraints(
        {"U1": (99, 50, 0)},
        {"U1": (10, 10)},
        {"min_spacing_mm": 1.27},
        page_size=(100, 100),
    )

    assert result["U1"] == (99, 50, 0)
    assert "建议分页" in diagnostics.violations[0]