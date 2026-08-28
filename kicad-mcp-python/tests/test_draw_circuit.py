"""L2 一键成图端到端测试：对当前打开的 eeschema 原理图调用 kicad_sch_draw_circuit。

用法: PYTHONPATH=src /home/luskyle/anaconda3/bin/python tests/test_draw_circuit.py
（要求 eeschema 已打开一个空 .kicad_sch，且已打原理图 API 补丁并编译）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
sys.path.insert(0, SRC)

from kicad_mcp.tools.circuit import (  # noqa: E402
    kicad_sch_auto_route,
    kicad_sch_draw_circuit,
)

RC = {
    "symbols": [
        {"ref": "V1", "lib": "Simulation_SPICE", "symbol": "VDC", "value": "5", "orient": 90},
        {"ref": "R1", "lib": "Device", "symbol": "R", "value": "10k", "orient": 90},
        {"ref": "C1", "lib": "Device", "symbol": "C", "value": "100u", "orient": 90},
        {"ref": "G1", "lib": "power", "symbol": "GND"},
    ],
    "nets": [
        {"name": "VIN", "pins": [["V1", "1"], ["R1", "1"]]},
        {"name": "OUT", "pins": [["R1", "2"], ["C1", "1"]], "label": "OUT"},
        {"name": "GND", "pins": [["C1", "2"], ["V1", "2"], ["G1", "1"]]},
    ],
    "layout": {"mode": "auto", "x0_mm": 50, "y0_mm": 50, "gap_mm": 0},
    "clear": True,
    "run_erc": True,
    "render": True,
    "max_fix_attempts": 3,
}

DIVIDER = {
    "symbols": [
        {"ref": "V1", "lib": "Simulation_SPICE", "symbol": "VDC", "value": "5", "orient": 90},
        {"ref": "R1", "lib": "Device", "symbol": "R", "value": "1k", "orient": 90},
        {"ref": "R2", "lib": "Device", "symbol": "R", "value": "2k", "orient": 90},
        {"ref": "G1", "lib": "power", "symbol": "GND"},
    ],
    "nets": [
        {"name": "VIN", "pins": [["V1", "1"], ["R1", "1"]]},
        {"name": "OUT", "pins": [["R1", "2"], ["R2", "1"]], "label": "OUT"},
        {"name": "GND", "pins": [["R2", "2"], ["V1", "2"], ["G1", "1"]]},
    ],
    "layout": {"mode": "auto", "x0_mm": 50, "y0_mm": 50, "gap_mm": 0},
    "clear": True,
    "run_erc": True,
    "render": True,
    "max_fix_attempts": 3,
}


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "rc"
    spec = RC if name == "rc" else DIVIDER
    print(f"=== 画 {name} 电路 ===")
    print(kicad_sch_draw_circuit(json.dumps(spec, ensure_ascii=False)))


if __name__ == "__main__":
    main()
