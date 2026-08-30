"""用新工具重画 keyboard-89 四页原理图。

用法（每页需先在该页打开 eeschema）:
    PYTHONPATH=src python tests/redraw_kb89.py flash
    PYTHONPATH=src python tests/redraw_kb89.py power
    PYTHONPATH=src python tests/redraw_kb89.py matrix
    PYTHONPATH=src python tests/redraw_kb89.py main
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
sys.path.insert(0, SRC)

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

MM = 10000
GRID = 1.27


def _g(x_mm):
    return round(x_mm / GRID) * GRID


def flash_json():
    return {
        "symbols": [
            {"ref": "U3", "lib": "keyboard-89_local", "symbol": "GD25Q16E",
             "value": "GD25Q16E", "footprint": "keyboard-89_local:SOIC-8_3.9x4.9mm_P1.27mm",
             "datasheet": "${KIPRJMOD}/SPIFlash-GD25Q16E-datasheet.pdf"},
            {"ref": "C20", "lib": "keyboard-89_local", "symbol": "C_GENERIC", "value": "100nF",
             "footprint": "keyboard-89_local:C_0402_1005Metric"},
        ],
        "nets": [
            {"name": "3V3", "pins": [["U3", "8"], ["C20", "1"]],
             "label": "3V3", "label_only": True},
            {"name": "0", "pins": [["U3", "4"], ["C20", "2"]],
             "label": "0", "label_only": True},
            {"name": "QSPI_CSn", "pins": [["U3", "1"]], "label": "QSPI_CSn"},
            {"name": "QSPI_SCLK", "pins": [["U3", "6"]], "label": "QSPI_SCLK"},
            {"name": "QSPI_SD0", "pins": [["U3", "5"]], "label": "QSPI_SD0"},
            {"name": "QSPI_SD1", "pins": [["U3", "2"]], "label": "QSPI_SD1"},
            {"name": "QSPI_SD2", "pins": [["U3", "3"]], "label": "QSPI_SD2"},
            {"name": "QSPI_SD3", "pins": [["U3", "7"]], "label": "QSPI_SD3"},
        ],
        "layout": {"mode": "grid", "columns": 2, "gap_mm": 25.4},
        "default_label_type": "global",
        "keep_power_symbols": True,
        "no_connect_marks": False,
        "clear": True, "run_erc": True, "render": True,
        "sheet": {"title": "Keyboard-89 QSPI Flash", "revision": "2.0",
                  "company": "Keyboard-89", "comment1": "GD25Q16E Quad-SPI boot flash"},
    }


def power_json():
    return {
        "symbols": [
            {"ref": "J1", "lib": "keyboard-89_local", "symbol": "USBC", "value": "USB-C",
             "footprint": "keyboard-89_local:USB_C_16P_2MD_073",
             "datasheet": "${KIPRJMOD}/C2765186_USB连接器_TYPE-C+16PIN+2MD(073)_规格书_TYPE-C+16PIN+2MD(073).PDF"},
            {"ref": "U2", "lib": "keyboard-89_local", "symbol": "LDO", "value": "AMS1117-3.3",
             "footprint": "keyboard-89_local:SOT-89-3", "datasheet": "${KIPRJMOD}/LDO.pdf"},
            *[{"ref": ref, "lib": "keyboard-89_local", "symbol": "C_GENERIC", "value": value,
               "footprint": f"keyboard-89_local:{footprint}"}
              for ref, value, footprint in (
                  ("C1", "10uF", "C_0805_2012Metric"),
                  ("C2", "10uF", "C_0805_2012Metric"),
                  ("C3", "100nF", "C_0402_1005Metric"))],
            *[{"ref": ref, "lib": "keyboard-89_local", "symbol": "R_GENERIC", "value": value,
               "footprint": "keyboard-89_local:R_0402_1005Metric"}
              for ref, value in (("R1", "5.1k"), ("R2", "5.1k"),
                                 ("R3", "27R"), ("R4", "27R"))],
                {"ref": "PWR0", "lib": "keyboard-89_local", "symbol": "POWER_FLAG", "value": "PWR_FLAG"},
            {"ref": "PWRV", "lib": "keyboard-89_local", "symbol": "POWER_FLAG", "value": "PWR_FLAG"},
        ],
        "nets": [
            {"name": "3V3", "pins": [["U2", "2"], ["C2", "1"], ["C3", "1"]],
             "label": "3V3", "label_only": True},
            {"name": "0", "pins": [["U2", "1"], ["C1", "2"], ["C2", "2"], ["C3", "2"],
                                   ["R1", "2"], ["R2", "2"], ["J1", "1"], ["J1", "12"],
                                   ["J1", "13"], ["J1", "14"], ["PWR0", "1"]], "label": "0"},
            {"name": "VBUS", "pins": [["U2", "3"], ["C1", "1"], ["J1", "2"], ["J1", "11"],
                                      ["PWRV", "1"]], "label": "VBUS"},
            {"name": "CC1", "pins": [["J1", "4"], ["R1", "1"]],
             "label_only": True, "label_type": "local"},
            {"name": "CC2", "pins": [["J1", "10"], ["R2", "1"]],
             "label_only": True, "label_type": "local"},
            {"name": "DM_C", "pins": [["J1", "5"], ["R3", "1"]],
             "label_only": True, "label_type": "local"},
            {"name": "DM_C", "pins": [["J1", "7"]],
             "label_type": "local", "label": "DM_C"},
            {"name": "DP_C", "pins": [["J1", "6"], ["R4", "1"]],
             "label_only": True, "label_type": "local"},
            {"name": "DP_C", "pins": [["J1", "8"]],
             "label_type": "local", "label": "DP_C"},
            {"name": "D-", "pins": [["R3", "2"]], "label": "D-", "label_spin": "left"},
            {"name": "D+", "pins": [["R4", "2"]], "label": "D+", "label_spin": "left"},
        ],
        "layout": {"mode": "positions", "positions": {
            "J1": [70.0, 100.0, 0],
            "R1": [125.0, 72.0, 0], "R2": [125.0, 128.0, 0],
            "R3": [125.0, 92.0, 0], "R4": [125.0, 108.0, 0],
            "U2": [205.0, 65.0, 0],
            "C1": [260.0, 45.0, 0], "C2": [260.0, 65.0, 0],
            "C3": [260.0, 85.0, 0],
            "PWRV": [205.0, 25.0, 0], "PWR0": [205.0, 150.0, 0],
        }},
        "default_label_type": "global",
        "label_size_mm": 0.5,
        "clearance_mm": 0.0,
        "keep_power_symbols": True,
        "no_connect_marks": True,
        "clear": True, "run_erc": True, "render": True,
        "sheet": {"title": "Keyboard-89 USB-C and Power", "revision": "2.0",
                  "company": "Keyboard-89", "comment1": "USB-C sink, 3.3 V regulator and USB termination"},
    }


def main_json():
    # RP2040 正确电源拓扑：IOVDD/USB_VDD/ADC_AVDD/VREG_VIN → 3V3，
    # DVDD(23,50) + VREG_VOUT(45) → 1V1；TESTEN(19) → 0；XIN/XOUT(20,21) → 晶振。
    symbols = [
        {"ref": "U1", "lib": "keyboard-89_local", "symbol": "RP2040", "value": "RP2040"},
        {"ref": "Y1", "lib": "keyboard-89_local", "symbol": "YXC", "value": "12MHz"},
        {"ref": "J2", "lib": "keyboard-89_local", "symbol": "PIN-5P", "value": "SWD"},
        *[{"ref": f"C{i}", "lib": "keyboard-89_local", "symbol": "C_GENERIC",
           "value": "1uF" if i in (9, 10) else ("15pF" if i in (13, 14) else "100nF")}
          for i in range(1, 15)],
        {"ref": "R5", "lib": "keyboard-89_local", "symbol": "R_GENERIC", "value": "100k"},
        {"ref": "SW_RST", "lib": "keyboard-89_local", "symbol": "TC-6601-5-160G", "value": "RESET"},
    ]
    nets = [
        {"name": "3V3", "label_only": True,
         "pins": [*[[f"C{i}", "1"] for i in range(1, 10)],
                  ["R5", "2"], ["J2", "1"], *[["U1", str(pin)] for pin in
                  (1, 10, 22, 33, 42, 43, 44, 48, 49)]]},
        {"name": "1V1", "label_only": True,
         "pins": [["U1", "23"], ["U1", "45"], ["U1", "50"],
                  ["C10", "1"], ["C11", "1"], ["C12", "1"]]},
        {"name": "0", "label_only": True,
         "pins": [*[[f"C{i}", "2"] for i in range(1, 15)],
                  ["J2", "4"], ["U1", "19"], ["U1", "57"],
                  ["Y1", "2"], ["Y1", "4"], ["SW_RST", "3"], ["SW_RST", "4"]]},
        {"name": "XIN", "label_only": True, "label_type": "local",
         "pins": [["U1", "20"], ["Y1", "1"], ["C13", "1"]]},
        {"name": "XOUT", "label_only": True, "label_type": "local",
         "pins": [["U1", "21"], ["Y1", "3"], ["C14", "1"]]},
        {"name": "SWCLK", "label_only": True, "label_type": "local",
         "pins": [["U1", "24"], ["J2", "3"]]},
        {"name": "SWD", "label_only": True, "label_type": "local",
         "pins": [["U1", "25"], ["J2", "2"]]},
        {"name": "RUN", "label_only": True, "label_type": "local",
         "pins": [["U1", "26"], ["J2", "5"], ["R5", "1"],
              ["SW_RST", "1"], ["SW_RST", "2"]]},
          *[{"name": name, "label_only": True, "pins": [["U1", str(pin)]],
              **({"label_spin": "left"} if name in ("D-", "D+") else {})}
          for name, pin in (("D-", 46), ("D+", 47), ("QSPI_CSn", 56),
                            ("QSPI_SCLK", 52), ("QSPI_SD0", 53), ("QSPI_SD1", 55),
                            ("QSPI_SD2", 54), ("QSPI_SD3", 51))],
        *[{"name": f"row{i}", "label_only": True, "pins": [["U1", str(2 + i)]]}
          for i in range(5)],
        *[{"name": f"column{i}", "label_only": True, "pins": [["U1", str(pin)]]}
          for i, pin in enumerate((7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18,
                                   27, 28, 29, 30, 31, 32, 34, 35, 36, 37, 38))],
    ]
    positions = {
        "U1": [100.0, 145.0, 0],
        **{f"C{i}": [180.0 + (i - 1) * 22.86, 50.0, 90] for i in range(1, 10)},
        "C10": [225.0, 100.0, 90], "C11": [270.0, 100.0, 90], "C12": [315.0, 100.0, 90],
        "C13": [45.0, 215.0, 90], "C14": [75.0, 215.0, 90], "Y1": [60.0, 245.0, 0],
        "J2": [155.0, 235.0, 0], "R5": [265.0, 205.0, 90], "SW_RST": [315.0, 205.0, 0],
    }
    return {
        "symbols": symbols,
        "nets": nets,
        "layout": {"mode": "positions", "positions": positions, "auto_center": False},
        "default_label_type": "global",
        "label_size_mm": 0.8,
        "keep_power_symbols": True,
        "no_connect_marks": True,
        "clearance_mm": 0.0,
        "clear": True, "run_erc": True, "render": True,
        "sheet": {"title": "Keyboard-89 RP2040 Core", "revision": "2.0",
                  "company": "Keyboard-89",
                  "comment1": "Clocks, decoupling, SWD, reset and matrix GPIO"},
    }


async def call(session, name, args) -> str:
    res = await session.call_tool(name, args)
    return "\n".join(getattr(c, "text", str(c)) for c in res.content)


async def redraw_main_manual(session) -> str:
    """通过 MCP 一次性绘制完整 RP2040 核心页。"""
    return await call(session, "kicad_sch_draw_circuit",
                      {"circuit_json": json.dumps(main_json())})


async def redraw_matrix(session) -> str:
    """矩阵页：15 键 3×5，每键每侧一个全局标签（Cx 列 / Rx 行）。

    走 kicad_sch_draw_circuit 的 label_only：同侧两脚自动短接、标签放外侧
    stub（不压符号）。间距 25.4mm（20 格）保证相邻标签互不碰撞、整体居中。
    """
    j = matrix_json()
    j.update(clear=True, run_erc=True, render=True)
    res = await call(session, "kicad_sch_draw_circuit",
                     {"circuit_json": json.dumps(j)})
    return res


def matrix_json():
    """矩阵页电路 spec（供 golden 回归复用；run_erc/render 由调用方覆盖）。

    间距 27.94mm（22 格）让相邻键的标签文字之间保持 ~3mm 净空（真实文字几何
    下 45 元素零重叠），布局整体居中在 420x297 页面。
    """
    col_of = {k: f"C{((k - 1) % 5) + 1}" for k in range(1, 16)}
    row_of = {k: f"R{(k - 1) // 5 + 1}" for k in range(1, 16)}
    x0, y0, dx, dy = 147.0, 118.0, 27.94, 27.94
    symbols = []
    positions = {}
    for k in range(1, 16):
        r = (k - 1) // 5
        c = (k - 1) % 5
        x, y = _g(x0 + c * dx), _g(y0 + r * dy)
        symbols.append({"ref": f"K{k}", "lib": "keyboard-89_local",
                        "symbol": "TC-6601-5-160G", "value": f"K{k}"})
        positions[f"K{k}"] = [x, y, 0]
    nets = []
    for c in range(1, 6):
        ks = [k for k in range(1, 16) if ((k - 1) % 5) + 1 == c]
        nets.append({"name": f"C{c}", "label_only": True,
                     "pins": [[f"K{k}", p] for k in ks for p in ("1", "2")]})
    for r in range(1, 4):
        ks = [k for k in range(1, 16) if (k - 1) // 5 + 1 == r]
        nets.append({"name": f"R{r}", "label_only": True,
                     "pins": [[f"K{k}", p] for k in ks for p in ("3", "4")]})
    return {
        "symbols": symbols,
        "nets": nets,
        "layout": {"mode": "positions", "positions": positions},
        "default_label_type": "global",
        # 图纸信息（右下角标题栏自动填充；draw_circuit 会自动居中到可用区、
        # 避开右下角标题栏）
        "sheet": {
            "title": "Keyboard-89 Matrix",
            "revision": "1.0",
            "company": "luskyle",
            "comment1": "15-key 3x5 keyboard matrix",
        },
    }


async def read_syms(session):
    from kicad_mcp.tools.schematic import _read_symbols
    return _read_symbols()


async def clear_all(session, item_types, prefixes):
    out = await call(session, "kicad_sch_get_items", {"item_types": item_types})
    import re
    cur = None
    n = 0
    for ln in out.splitlines():
        m = re.search(r"id=([0-9a-f-]{36})", ln)
        if m:
            cur = m.group(1)
        if cur and any(ln.startswith(p) or f" {p}" in ln for p in prefixes):
            await call(session, "kicad_sch_delete_item", {"item_id": cur})
            n += 1
            cur = None
    return n


async def main() -> None:
    page = sys.argv[1] if len(sys.argv) > 1 else "flash"
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "kicad_mcp"],
        env={**os.environ, "PYTHONPATH": SRC},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(f"===== 重画页面: {page} =====")
            if page == "matrix":
                print(await redraw_matrix(session))
            elif page == "main":
                print(await redraw_main_manual(session))
            else:
                j = {"flash": flash_json, "power": power_json}[page]()
                res = await call(session, "kicad_sch_draw_circuit", {"circuit_json": json.dumps(j)})
                print(res)
            print("===== 保存 =====")
            print(await call(session, "kicad_save_document", {}))


if __name__ == "__main__":
    asyncio.run(main())
