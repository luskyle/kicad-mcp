"""Net-owned occupancy grid and orthogonal A* routing."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from .geometry import Box

Point = tuple[int, int]
Segment = tuple[Point, Point]


@dataclass
class OccupancyGrid:
    grid_mm: float = 1.27
    owners: dict[Point, str] = field(default_factory=dict)

    def point_to_cell(self, point: tuple[float, float]) -> Point:
        return round(point[0] / self.grid_mm), round(point[1] / self.grid_mm)

    def cell_to_point(self, cell: Point) -> tuple[float, float]:
        return cell[0] * self.grid_mm, cell[1] * self.grid_mm

    def occupy_box(self, box: Box, owner: str = "#obstacle") -> None:
        left, top = self.point_to_cell((box.left, box.top))
        right, bottom = self.point_to_cell((box.right, box.bottom))
        for x_cell in range(left, right + 1):
            for y_cell in range(top, bottom + 1):
                self.owners[(x_cell, y_cell)] = owner

    def occupy_segment(self, segment: Segment, owner: str) -> None:
        (x1, y1), (x2, y2) = segment
        if x1 != x2 and y1 != y2:
            raise ValueError("占用网格只接受正交线段")
        if x1 == x2:
            cells = ((x1, y) for y in range(min(y1, y2), max(y1, y2) + 1))
        else:
            cells = ((x, y1) for x in range(min(x1, x2), max(x1, x2) + 1))
        for cell in cells:
            existing = self.owners.get(cell)
            if existing not in (None, owner):
                raise RuntimeError(f"网格 {cell} 已由 {existing} 占用，不能分配给 {owner}")
            self.owners[cell] = owner

    def blocked(self, cell: Point, owner: str) -> bool:
        return self.owners.get(cell) not in (None, owner)


def _compress_path(path: list[Point]) -> list[Segment]:
    if len(path) < 2:
        return []
    segments = []
    start = path[0]
    previous = path[0]
    direction = None
    for point in path[1:]:
        current_direction = (point[0] - previous[0], point[1] - previous[1])
        if direction is not None and current_direction != direction:
            segments.append((start, previous))
            start = previous
        direction = current_direction
        previous = point
    segments.append((start, previous))
    return segments


def find_orthogonal_path(
    grid: OccupancyGrid,
    start: tuple[float, float],
    goal: tuple[float, float],
    owner: str,
    *,
    margin_cells: int = 30,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Find and compress a shortest four-neighbor path for one net."""
    start_cell = grid.point_to_cell(start)
    goal_cell = grid.point_to_cell(goal)
    min_x = min(start_cell[0], goal_cell[0]) - margin_cells
    max_x = max(start_cell[0], goal_cell[0]) + margin_cells
    min_y = min(start_cell[1], goal_cell[1]) - margin_cells
    max_y = max(start_cell[1], goal_cell[1]) + margin_cells
    frontier = [(0, 0, start_cell)]
    came_from: dict[Point, Point | None] = {start_cell: None}
    cost = {start_cell: 0}
    serial = 0
    while frontier:
        _, _, current = heapq.heappop(frontier)
        if current == goal_cell:
            break
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            neighbor = current[0] + dx, current[1] + dy
            if not (min_x <= neighbor[0] <= max_x and min_y <= neighbor[1] <= max_y):
                continue
            if neighbor not in (start_cell, goal_cell) and grid.blocked(neighbor, owner):
                continue
            next_cost = cost[current] + 1
            if next_cost >= cost.get(neighbor, 1 << 30):
                continue
            cost[neighbor] = next_cost
            came_from[neighbor] = current
            heuristic = abs(goal_cell[0] - neighbor[0]) + abs(goal_cell[1] - neighbor[1])
            serial += 1
            heapq.heappush(frontier, (next_cost + heuristic, serial, neighbor))
    if goal_cell not in came_from:
        raise RuntimeError(f"网络 {owner} 在占用网格中无可用路径")
    path = []
    current: Point | None = goal_cell
    while current is not None:
        path.append(current)
        current = came_from[current]
    path.reverse()
    segments = _compress_path(path)
    for segment in segments:
        grid.occupy_segment(segment, owner)
    return [(grid.cell_to_point(a), grid.cell_to_point(b)) for a, b in segments]


def validate_routed_segments(routes: dict[str, list[Segment]]) -> list[str]:
    """Detect malformed segments and electrical contact between foreign nets."""
    issues = []
    seen: dict[tuple[Point, Point], str] = {}
    normalized: list[tuple[str, Point, Point]] = []
    for net, segments in routes.items():
        for start, end in segments:
            if start == end:
                issues.append(f"{net}: 零长度线段 {start}")
                continue
            if start[0] != end[0] and start[1] != end[1]:
                issues.append(f"{net}: 非正交线段 {start}->{end}")
                continue
            key = tuple(sorted((start, end)))
            if key in seen:
                issues.append(f"{net}: 与 {seen[key]} 重复线段 {start}->{end}")
            else:
                seen[key] = net
            normalized.append((net, start, end))
    for index, (net_a, a1, a2) in enumerate(normalized):
        for net_b, b1, b2 in normalized[index + 1:]:
            if net_a == net_b:
                continue
            if a1[1] == a2[1] == b1[1] == b2[1]:
                overlap = max(min(a1[0], a2[0]), min(b1[0], b2[0])) < min(
                    max(a1[0], a2[0]), max(b1[0], b2[0])
                )
                if overlap:
                    issues.append(f"{net_a}/{net_b}: 异网水平共线重叠")
            elif a1[0] == a2[0] == b1[0] == b2[0]:
                overlap = max(min(a1[1], a2[1]), min(b1[1], b2[1])) < min(
                    max(a1[1], a2[1]), max(b1[1], b2[1])
                )
                if overlap:
                    issues.append(f"{net_a}/{net_b}: 异网垂直共线重叠")
            else:
                horizontal = (net_a, a1, a2, net_b, b1, b2) if a1[1] == a2[1] else (
                    net_b, b1, b2, net_a, a1, a2
                )
                hnet, h1, h2, vnet, v1, v2 = horizontal
                crossing = (
                    min(h1[0], h2[0]) <= v1[0] <= max(h1[0], h2[0])
                    and min(v1[1], v2[1]) <= h1[1] <= max(v1[1], v2[1])
                )
                if crossing and ((v1[0], h1[1]) in (h1, h2, v1, v2)):
                    issues.append(f"{hnet}/{vnet}: 异网 T 接于 {(v1[0], h1[1])}")
    return issues