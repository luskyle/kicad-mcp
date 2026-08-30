from __future__ import annotations

import pytest

from kicad_mcp.tools.circuit import MM, _route_net_trunk, _route_priority
from kicad_mcp.tools.geometry import Box
from kicad_mcp.tools.pathfinding import (
    OccupancyGrid,
    find_orthogonal_path,
    validate_routed_segments,
)


def test_astar_routes_around_owned_obstacle() -> None:
    grid = OccupancyGrid(grid_mm=1.0)
    grid.occupy_box(Box(2, -1, 4, 1))

    path = find_orthogonal_path(grid, (0, 0), (6, 0), "N1")

    assert len(path) >= 3
    assert path[0][0] == (0, 0)
    assert path[-1][1] == (6, 0)
    assert all(a[0] == b[0] or a[1] == b[1] for a, b in path)


def test_grid_rejects_foreign_net_ownership() -> None:
    grid = OccupancyGrid(grid_mm=1.0)
    grid.occupy_segment(((0, 0), (4, 0)), "N1")

    with pytest.raises(RuntimeError, match="N1 占用"):
        grid.occupy_segment(((2, 0), (2, 3)), "N2")


def test_route_priority_orders_power_then_high_fanout() -> None:
    nets = [
        {"name": "SIG", "pins": [["A", "1"]]},
        {"name": "GND", "pins": [["A", "2"], ["B", "1"]]},
        {"name": "BUS", "pins": [["A", "3"], ["B", "2"], ["C", "1"]]},
    ]

    assert [net["name"] for net in sorted(nets, key=_route_priority)] == [
        "GND", "BUS", "SIG"
    ]


def test_mult_pin_net_can_use_astar_chain() -> None:
    points = [
        ("A", (0, 0)),
        ("B", (round(5.08 * MM), 0)),
        ("C", (round(5.08 * MM), round(5.08 * MM))),
    ]
    used = []

    segments, lane, junctions = _route_net_trunk(
        points,
        [],
        [],
        {},
        used_segs_iu=used,
        enable_pathfinding=True,
        net_name="BUS",
    )

    assert lane is None
    assert junctions == []
    assert segments == used
    assert not validate_routed_segments({"BUS": segments})


@pytest.mark.parametrize(
    ("routes", "message"),
    [
        ({"N1": [((0, 0), (0, 0))]}, "零长度"),
        ({"N1": [((0, 0), (1, 1))]}, "非正交"),
        ({"N1": [((0, 0), (4, 0))], "N2": [((2, 0), (6, 0))]}, "共线重叠"),
        ({"N1": [((0, 0), (4, 0))], "N2": [((2, 0), (2, 3))]}, "异网 T 接"),
    ],
)
def test_route_preflight_rejects_invalid_topology(routes: dict, message: str) -> None:
    assert any(message in issue for issue in validate_routed_segments(routes))