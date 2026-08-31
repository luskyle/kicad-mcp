"""Draw separate series-RLC and diode-isolated 7x7 matrix pages.

Open the target page in repository Eeschema, then run this script with either
``rlc`` or ``matrix``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SRC = str(Path(__file__).resolve().parent.parent / "src")
sys.path.insert(0, SRC)

from kicad_mcp.tools.schematic import MM, _read_symbols

GRID = 1.27
ROWS = 7
COLS = 7


def grid(value: float) -> float:
    return round(value / GRID) * GRID


def rlc_spec() -> dict:
    return {
        "symbols": [
        {"ref": "R1", "lib": "Device", "symbol": "R", "value": "1k"},
        {"ref": "L1", "lib": "Device", "symbol": "L", "value": "10mH"},
        {"ref": "C1", "lib": "Device", "symbol": "C", "value": "100nF"},
        ],
        "nets": [
            {"name": "VIN", "pins": [["R1", "1"]], "label": "VIN"},
            {"name": "R_L", "pins": [["R1", "2"], ["L1", "1"]]},
            {"name": "VOUT", "pins": [["L1", "2"], ["C1", "1"]],
             "label": "VOUT"},
            {"name": "0", "pins": [["C1", "2"]], "label": "0"},
        ],
        "layout": {"mode": "positions", "positions": {
            "R1": [grid(90.0), grid(80.0), 90],
            "L1": [grid(140.0), grid(80.0), 90],
            "C1": [grid(190.0), grid(80.0), 90],
        }},
        "default_label_type": "global",
        "clear": True,
        "run_erc": True,
        "render": True,
        "sheet": {
            "title": "Series RLC Circuit",
            "revision": "1.1",
            "company": "kicad-mcp",
            "comment1": "R1 1k, L1 10mH, C1 100nF",
        },
    }


def matrix_spec() -> dict:
    symbols = []
    positions = {}
    nets = []

    x0 = 35.0
    y0 = 45.0
    x_gap = 35.0
    y_gap = 18.0
    diode_dx = 15.24

    for row in range(1, ROWS + 1):
        for col in range(1, COLS + 1):
            index = (row - 1) * COLS + col
            switch_ref = f"SW{index}"
            diode_ref = f"D{index}"
            x = grid(x0 + (col - 1) * x_gap)
            y = grid(y0 + (row - 1) * y_gap)
            symbols.extend([
                {"ref": switch_ref, "lib": "Switch", "symbol": "SW_Push",
                 "value": f"K{row}{col}"},
                {"ref": diode_ref, "lib": "Device", "symbol": "D",
                 "value": "1N4148", "orient": 0},
            ])
            positions[switch_ref] = [x, y, 0]
            positions[diode_ref] = [grid(x + diode_dx), y, 0]
            nets.append({
                "name": f"KEY_{row}_{col}",
                "pins": [[switch_ref, "2"], [diode_ref, "1"]],
            })

    return {
        "symbols": symbols,
        "nets": nets,
        "layout": {
            "mode": "positions",
            "positions": positions,
            "auto_center": False,
        },
        "default_label_type": "global",
        "label_size_mm": 1.0,
        "clearance_mm": 0.0,
        "no_connect_marks": False,
        "clear": True,
        "run_erc": False,
        "render": False,
        "sheet": {
            "title": "7x7 Keyboard Matrix",
            "revision": "1.1",
            "company": "kicad-mcp",
            "comment1": "49-key diode-isolated matrix; ROW1..ROW7 / COL1..COL7",
        },
    }


async def call(session: ClientSession, name: str, arguments: dict) -> str:
    result = await session.call_tool(name, arguments)
    return "\n".join(getattr(item, "text", str(item)) for item in result.content)


async def add_matrix_labels(session: ClientSession) -> None:
    symbols = _read_symbols()
    stub = 3.81
    for row in range(1, ROWS + 1):
        for col in range(1, COLS + 1):
            index = (row - 1) * COLS + col
            switch_x, switch_y = symbols[f"SW{index}"]["pins"]["1"]
            diode_x, diode_y = symbols[f"D{index}"]["pins"]["2"]
            switch_x_mm, switch_y_mm = switch_x / MM, switch_y / MM
            diode_x_mm, diode_y_mm = diode_x / MM, diode_y / MM

            await call(session, "kicad_sch_add_line", {
                "x1_mm": switch_x_mm,
                "y1_mm": switch_y_mm,
                "x2_mm": switch_x_mm - stub,
                "y2_mm": switch_y_mm,
            })
            await call(session, "kicad_sch_add_label", {
                "label_type": "global",
                "text": f"ROW{row}",
                "x_mm": switch_x_mm - stub,
                "y_mm": switch_y_mm,
                "height_mm": 0.6,
                "spin": "left",
            })
            await call(session, "kicad_sch_add_line", {
                "x1_mm": diode_x_mm,
                "y1_mm": diode_y_mm,
                "x2_mm": diode_x_mm,
                "y2_mm": diode_y_mm - stub,
            })
            await call(session, "kicad_sch_add_label", {
                "label_type": "global",
                "text": f"COL{col}",
                "x_mm": diode_x_mm,
                "y_mm": diode_y_mm - stub,
                "height_mm": 0.6,
                "spin": "up",
            })


async def main() -> None:
    page = sys.argv[1] if len(sys.argv) > 1 else "matrix"
    if page not in {"rlc", "matrix"}:
        raise SystemExit("usage: draw_rlc_7x7_matrix.py [rlc|matrix]")

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(await call(
                session,
                "kicad_sch_draw_circuit",
                {"circuit_json": json.dumps(
                    rlc_spec() if page == "rlc" else matrix_spec()
                )},
            ))
            if page == "matrix":
                await add_matrix_labels(session)
            print(await call(session, "kicad_save_document", {}))


if __name__ == "__main__":
    asyncio.run(main())
