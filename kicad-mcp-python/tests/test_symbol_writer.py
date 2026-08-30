from __future__ import annotations

from kicad_mcp.symbol_writer import GRID, layout_pins


def test_generated_pin_connections_are_on_grid() -> None:
    pins = [
        {"number": "1", "name": "1", "type": "passive"},
        {"number": "2", "name": "2", "type": "passive"},
        {"number": "3", "name": "VBUS", "type": "power_in"},
        {"number": "4", "name": "GND", "type": "power_in"},
        {"number": "57", "name": "VREG_VOUT", "type": "power_out"},
    ]

    layout = layout_pins(pins, value_name="LONG_GENERIC_SYMBOL_NAME")

    for pin in layout["pins"]:
        assert pin["x"] / GRID == round(pin["x"] / GRID)
        assert pin["y"] / GRID == round(pin["y"] / GRID)