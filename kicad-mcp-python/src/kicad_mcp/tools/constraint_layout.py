"""Constraint post-processing for topology-based schematic layouts."""

from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import Box


@dataclass
class LayoutDiagnostics:
    stages: list[str] = field(default_factory=list)
    expanded_axes: int = 0
    violations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "stages": self.stages,
            "expanded_axes": self.expanded_axes,
            "violations": self.violations,
        }


def _snap(value: float, grid_mm: float) -> float:
    return round(value / grid_mm) * grid_mm


def _symbol_box(position: tuple, size: tuple[float, float]) -> Box:
    x_mm, y_mm, _ = position
    width, height = size
    return Box(x_mm - width / 2, y_mm - height / 2,
               x_mm + width / 2, y_mm + height / 2)


def apply_constraints(
    layout: dict[str, tuple],
    sizes: dict[str, tuple[float, float]],
    constraints: dict | None,
    *,
    grid_mm: float = 1.27,
    page_size: tuple[float, float] | None = None,
) -> tuple[dict[str, tuple], LayoutDiagnostics]:
    """Apply alignment, fixed-position, spacing and keepout constraints."""
    result = dict(layout)
    diagnostics = LayoutDiagnostics(stages=["topology", "ordering"])
    constraints = constraints or {}
    if not constraints:
        diagnostics.stages.extend(["sizing", "packing"])
        return result, diagnostics

    for ref, position in (constraints.get("fixed") or {}).items():
        if ref not in result:
            diagnostics.violations.append(f"固定位置引用不存在: {ref}")
            continue
        orientation = position[2] if len(position) > 2 else result[ref][2]
        result[ref] = (_snap(float(position[0]), grid_mm),
                       _snap(float(position[1]), grid_mm), orientation)

    row_groups = list(constraints.get("same_row", []))
    row_groups.extend(constraints.get("groups", []))
    for refs in row_groups:
        valid = [ref for ref in refs if ref in result]
        if valid:
            target = _snap(sum(result[ref][1] for ref in valid) / len(valid), grid_mm)
            for ref in valid:
                result[ref] = (result[ref][0], target, result[ref][2])

    for refs in constraints.get("same_column", []):
        valid = [ref for ref in refs if ref in result]
        if valid:
            target = _snap(sum(result[ref][0] for ref in valid) / len(valid), grid_mm)
            for ref in valid:
                result[ref] = (target, result[ref][1], result[ref][2])

    minimum = float(constraints.get("min_spacing_mm", 1.27))
    ordered = sorted(result, key=lambda ref: (result[ref][0], result[ref][1], ref))
    for index, ref in enumerate(ordered):
        if ref in (constraints.get("fixed") or {}):
            continue
        box = _symbol_box(result[ref], sizes.get(ref, (10.0, 10.0)))
        while any(
            box.overlaps(
                _symbol_box(result[other], sizes.get(other, (10.0, 10.0))),
                minimum,
            )
            for other in ordered[:index]
        ):
            x_mm, y_mm, orientation = result[ref]
            result[ref] = (x_mm, _snap(y_mm + grid_mm, grid_mm), orientation)
            box = _symbol_box(result[ref], sizes.get(ref, (10.0, 10.0)))
            diagnostics.expanded_axes += 1

    keepouts = [Box(*map(float, values)) for values in constraints.get("keepouts", [])]
    for ref in ordered:
        box = _symbol_box(result[ref], sizes.get(ref, (10.0, 10.0)))
        attempts = 0
        while any(box.overlaps(keepout, minimum) for keepout in keepouts):
            x_mm, y_mm, orientation = result[ref]
            result[ref] = (_snap(x_mm + grid_mm, grid_mm), y_mm, orientation)
            box = _symbol_box(result[ref], sizes.get(ref, (10.0, 10.0)))
            attempts += 1
            if attempts > 1000:
                diagnostics.violations.append(f"{ref}: 无法避开禁止区")
                break

    diagnostics.stages.append("sizing")
    if page_size:
        page_width, page_height = page_size
        for ref, position in result.items():
            box = _symbol_box(position, sizes.get(ref, (10.0, 10.0)))
            if box.left < 0 or box.top < 0 or box.right > page_width or box.bottom > page_height:
                diagnostics.violations.append(
                    f"{ref}: 超出 {page_width:g}x{page_height:g}mm 页面，建议分页"
                )
    diagnostics.stages.append("packing")
    return result, diagnostics