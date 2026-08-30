"""Geometry primitives and clearance checks for schematic drawing."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot


@dataclass(frozen=True)
class Box:
    left: float
    top: float
    right: float
    bottom: float

    def expanded(self, clearance_mm: float) -> "Box":
        return Box(
            self.left - clearance_mm,
            self.top - clearance_mm,
            self.right + clearance_mm,
            self.bottom + clearance_mm,
        )

    def overlaps(self, other: "Box", clearance_mm: float = 0.0) -> bool:
        expanded = self.expanded(clearance_mm)
        return not (
            expanded.right <= other.left
            or other.right <= expanded.left
            or expanded.bottom <= other.top
            or other.bottom <= expanded.top
        )

    def clearance_to(self, other: "Box") -> float:
        dx = max(other.left - self.right, self.left - other.right, 0.0)
        dy = max(other.top - self.bottom, self.top - other.bottom, 0.0)
        return hypot(dx, dy)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return self.left, self.top, self.right, self.bottom


@dataclass(frozen=True)
class GeometryModel:
    label_label_clearance_mm: float = 1.27
    label_symbol_clearance_mm: float = 1.27
    wire_symbol_clearance_mm: float = 1.27

    @staticmethod
    def text_extent(text: str, height_mm: float) -> tuple[float, float]:
        return max(height_mm, len(text) * height_mm * 0.62), height_mm

    @classmethod
    def label_box(
        cls,
        text: str,
        x_mm: float,
        y_mm: float,
        height_mm: float = 1.27,
        spin: str = "left",
        shape: str = "local",
    ) -> Box:
        """Approximate KiCad label shape and text bounds for all four spins."""
        text_width, text_height = cls.text_extent(text, height_mm)
        shape_depth = 1.5 if shape in {"global", "hier", "directive"} else 0.0
        text_offset = 1.43
        extent = text_offset + text_width + shape_depth
        half_height = max(text_height / 2, shape_depth / 2)
        spin = spin.lower()
        if spin == "left":
            return Box(x_mm - shape_depth, y_mm - half_height,
                       x_mm + extent, y_mm + half_height)
        if spin == "right":
            return Box(x_mm - extent, y_mm - half_height,
                       x_mm + shape_depth, y_mm + half_height)
        if spin == "up":
            return Box(x_mm - half_height, y_mm - extent,
                       x_mm + half_height, y_mm + shape_depth)
        if spin == "down":
            return Box(x_mm - half_height, y_mm - shape_depth,
                       x_mm + half_height, y_mm + extent)
        raise ValueError(f"不支持的标签 spin: {spin}")

    @staticmethod
    def segment_box(
        start: tuple[float, float],
        end: tuple[float, float],
        width_mm: float = 0.0,
    ) -> Box:
        half_width = width_mm / 2
        return Box(
            min(start[0], end[0]) - half_width,
            min(start[1], end[1]) - half_width,
            max(start[0], end[0]) + half_width,
            max(start[1], end[1]) + half_width,
        )

    @staticmethod
    def symbol_box(
        pin_positions: list[tuple[float, float]],
        center: tuple[float, float],
        padding_mm: float = 0.5,
    ) -> Box:
        if not pin_positions:
            return Box(center[0] - 2.54, center[1] - 2.54,
                       center[0] + 2.54, center[1] + 2.54)
        return Box(
            min(point[0] for point in pin_positions) - padding_mm,
            min(point[1] for point in pin_positions) - padding_mm,
            max(point[0] for point in pin_positions) + padding_mm,
            max(point[1] for point in pin_positions) + padding_mm,
        )

    @staticmethod
    def junction_box(
        point: tuple[float, float], radius_mm: float = 0.5
    ) -> Box:
        return Box(point[0] - radius_mm, point[1] - radius_mm,
                   point[0] + radius_mm, point[1] + radius_mm)

    def violation(self, first: Box, second: Box, kind: str) -> bool:
        clearance = {
            "label_label": self.label_label_clearance_mm,
            "label_symbol": self.label_symbol_clearance_mm,
            "wire_symbol": self.wire_symbol_clearance_mm,
        }[kind]
        return first.overlaps(second, clearance)