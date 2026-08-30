"""Measurements extracted from KiCad SVG output."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .geometry import Box

_POINT_COMMAND = re.compile(r"[ML]\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _float(value: str | None, default: float = 0.0) -> float:
    match = _NUMBER.search(value or "")
    return float(match.group()) if match else default


def analyze_svg(svg_file: str | Path) -> dict:
    """Return page, ink and text-clearance metrics from an exported SVG."""
    root = ET.parse(svg_file).getroot()
    viewbox = [_float(value) for value in root.attrib.get("viewBox", "").split()]
    drawable_tags = {"path", "line", "polyline", "polygon", "rect", "circle", "text"}
    drawable = []
    points: list[tuple[float, float]] = []
    text_boxes: list[Box] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in drawable_tags:
            continue
        drawable.append(element)
        if tag == "path":
            points.extend(
                (float(x_value), float(y_value))
                for x_value, y_value in _POINT_COMMAND.findall(element.attrib.get("d", ""))
            )
        elif tag == "line":
            points.extend([
                (_float(element.attrib.get("x1")), _float(element.attrib.get("y1"))),
                (_float(element.attrib.get("x2")), _float(element.attrib.get("y2"))),
            ])
        elif tag == "circle":
            x_value = _float(element.attrib.get("cx"))
            y_value = _float(element.attrib.get("cy"))
            radius = _float(element.attrib.get("r"))
            points.extend([(x_value - radius, y_value - radius),
                           (x_value + radius, y_value + radius)])
        elif tag == "rect":
            x_value = _float(element.attrib.get("x"))
            y_value = _float(element.attrib.get("y"))
            width = _float(element.attrib.get("width"))
            height = _float(element.attrib.get("height"))
            points.extend([(x_value, y_value), (x_value + width, y_value + height)])
        elif tag == "text":
            text = "".join(element.itertext()).strip()
            x_value = _float(element.attrib.get("x"))
            y_value = _float(element.attrib.get("y"))
            size = _float(element.attrib.get("font-size"), 1.27)
            width = max(size, len(text) * size * 0.62)
            box = Box(x_value, y_value - size, x_value + width, y_value)
            text_boxes.append(box)
            points.extend([(box.left, box.top), (box.right, box.bottom)])
    ink_bounds = None
    if points:
        ink_bounds = [
            min(point[0] for point in points),
            min(point[1] for point in points),
            max(point[0] for point in points),
            max(point[1] for point in points),
        ]
    minimum_text_clearance = None
    for index, first in enumerate(text_boxes):
        for second in text_boxes[index + 1:]:
            clearance = first.clearance_to(second)
            if minimum_text_clearance is None or clearance < minimum_text_clearance:
                minimum_text_clearance = clearance
    inside_page = True
    if len(viewbox) == 4 and ink_bounds:
        x_value, y_value, width, height = viewbox
        inside_page = (
            x_value <= ink_bounds[0] <= ink_bounds[2] <= x_value + width
            and y_value <= ink_bounds[1] <= ink_bounds[3] <= y_value + height
        )
    return {
        "drawable_elements": len(drawable),
        "text_elements": len(text_boxes),
        "viewbox": viewbox,
        "ink_bounds": ink_bounds,
        "inside_page": inside_page,
        "minimum_text_clearance_mm": minimum_text_clearance,
    }