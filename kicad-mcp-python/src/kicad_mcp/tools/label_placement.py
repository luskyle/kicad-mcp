"""Discrete candidate solver for schematic labels."""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import Box, GeometryModel


@dataclass(frozen=True)
class LabelCandidate:
    x_mm: float
    y_mm: float
    spin: str
    stub_mm: float
    cost: float


_DIRECTIONS = {
    "left": (-1, 0),
    "right": (1, 0),
    "up": (0, -1),
    "down": (0, 1),
}


def solve_label_candidate(
    text: str,
    pin: tuple[float, float],
    obstacles: list[Box],
    *,
    height_mm: float = 1.27,
    clearance_mm: float = 1.27,
    preferred_spin: str | None = None,
    shape: str = "local",
    page_box: Box | None = None,
    grid_mm: float = 1.27,
    wires: list[tuple[tuple[float, float], tuple[float, float]]] | None = None,
    alignment_points: list[tuple[float, float]] | None = None,
) -> LabelCandidate:
    """Choose among four directions and grid-aligned stubs up to 10.16 mm."""
    candidates = []
    spins = list(_DIRECTIONS)
    if preferred_spin in _DIRECTIONS:
        spins.remove(preferred_spin)
        spins.insert(0, preferred_spin)
    for spin_index, spin in enumerate(spins):
        dx, dy = _DIRECTIONS[spin]
        for steps in range(1, 9):
            stub = steps * grid_mm
            x_mm = round((pin[0] + dx * stub) / grid_mm) * grid_mm
            y_mm = round((pin[1] + dy * stub) / grid_mm) * grid_mm
            box = GeometryModel.label_box(text, x_mm, y_mm, height_mm, spin, shape)
            collisions = sum(box.overlaps(obstacle, clearance_mm) for obstacle in obstacles)
            stub_box = GeometryModel.segment_box(pin, (x_mm, y_mm))
            wire_crossings = sum(
                stub_box.overlaps(GeometryModel.segment_box(start, end))
                for start, end in (wires or [])
            )
            out = 0
            if page_box and not (
                page_box.left <= box.left <= box.right <= page_box.right
                and page_box.top <= box.top <= box.bottom <= page_box.bottom
            ):
                out = 1
            alignment_cost = min(
                (abs(x_mm - point[0]) + abs(y_mm - point[1])
                 for point in (alignment_points or [])),
                default=0.0,
            )
            cost = (
                collisions * 10000
                + out * 10000
                + wire_crossings * 100
                + steps
                + spin_index * 0.1
                + alignment_cost * 0.01
            )
            candidates.append(LabelCandidate(x_mm, y_mm, spin, stub, cost))
    best = min(candidates, key=lambda candidate: candidate.cost)
    if best.cost >= 10000:
        raise RuntimeError(f"标签 {text} 无满足 {clearance_mm:g}mm 净距的候选位置")
    return best