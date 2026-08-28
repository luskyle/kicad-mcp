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
            {"ref": "U3", "lib": "keyboard-89_local", "symbol": "GD25Q16E", "value": "GD25Q16E"},
            {"ref": "PWR3", "lib": "power", "symbol": "PWR_FLAG", "value": "PWR_FLAG"},
            {"ref": "PWR0", "lib": "power", "symbol": "PWR_FLAG", "value": "PWR_FLAG"},
        ],
        "nets": [
            {"name": "3V3", "pins": [["PWR3", "1"], ["U3", "3"], ["U3", "7"], ["U3", "8"]], "label": "3V3"},
            {"name": "0", "pins": [["PWR0", "1"], ["U3", "4"]], "label": "0"},
            {"name": "FLASH_CS", "pins": [["U3", "1"]], "label": "FLASH_CS"},
            {"name": "FLASH_SCLK", "pins": [["U3", "6"]], "label": "FLASH_SCLK"},
            {"name": "FLASH_SD0", "pins": [["U3", "5"]], "label": "FLASH_SD0"},
            {"name": "FLASH_SD1", "pins": [["U3", "2"]], "label": "FLASH_SD1"},
        ],
        "layout": {"mode": "auto"},
        "default_label_type": "global",
        "keep_power_symbols": True,
        "no_connect_marks": True,
        "clear": True, "run_erc": True, "render": True,
    }


def power_json():
    return {
        "symbols": [
            {"ref": "J1", "lib": "keyboard-89_local", "symbol": "USBC", "value": "USB-C"},
            {"ref": "U2", "lib": "keyboard-89_local", "symbol": "LDO", "value": "ME6211C33"},
            {"ref": "C1", "lib": "keyboard-89_local", "symbol": "C-100nF", "value": "100nF"},
            {"ref": "PWR0", "lib": "power", "symbol": "PWR_FLAG", "value": "PWR_FLAG"},
            {"ref": "PWRV", "lib": "power", "symbol": "PWR_FLAG", "value": "PWR_FLAG"},
        ],
        "nets": [
            # 3V3 由 LDO 输出驱动，不需要 PWR_FLAG（两个 power_out 同网会报错）
            {"name": "3V3", "pins": [["U2", "2"], ["C1", "1"]], "label": "3V3"},
            # 修正原图 bug：USBC 的 GND(1,12)+SHELL(13,14) 才接 0，VBUS(2,11) 接 VBUS
            {"name": "0", "pins": [["U2", "1"], ["C1", "2"], ["J1", "1"], ["J1", "12"],
                                   ["J1", "13"], ["J1", "14"], ["PWR0", "1"]], "label": "0"},
            {"name": "VBUS", "pins": [["U2", "3"], ["J1", "2"], ["J1", "11"], ["PWRV", "1"]], "label": "VBUS"},
            {"name": "USB_DM", "pins": [["J1", "7"]], "label": "USB_DM"},
            {"name": "USB_DP", "pins": [["J1", "6"]], "label": "USB_DP"},
        ],
        # 横排（信号流左→右，IEC 61082）：J1(USBC)→U2(LDO)→C1，trunk 有干净通道
        "layout": {"mode": "grid", "columns": 1, "gap_mm": 20},
        "default_label_type": "global",
        "keep_power_symbols": True,
        "no_connect_marks": True,
        "clear": True, "run_erc": True, "render": True,
    }


def main_json():
    # RP2040 正确电源拓扑：IOVDD/USB_VDD/ADC_AVDD/VREG_VIN → 3V3，
    # DVDD(23,50) + VREG_VOUT(45) → 1V1；TESTEN(19) → 0；XIN/XOUT(20,21) → 晶振。
    return {
        "symbols": [
            {"ref": "U1", "lib": "keyboard-89_local", "symbol": "RP2040", "value": "RP2040"},
            {"ref": "Y1", "lib": "keyboard-89_local", "symbol": "YXC", "value": "12MHz"},
            {"ref": "J2", "lib": "keyboard-89_local", "symbol": "PIN-5P", "value": "SWD"},
            {"ref": "C1", "lib": "Device", "symbol": "C", "value": "100nF"},
            {"ref": "C2", "lib": "Device", "symbol": "C", "value": "100nF"},
            {"ref": "C3", "lib": "Device", "symbol": "C", "value": "100nF"},
            {"ref": "R1", "lib": "Device", "symbol": "R", "value": "100k"},
            {"ref": "PWR3", "lib": "power", "symbol": "PWR_FLAG", "value": "PWR_FLAG"},
            {"ref": "PWRG", "lib": "power", "symbol": "PWR_FLAG", "value": "PWR_FLAG"},
        ],
        "nets": [
            {"name": "3V3", "pins": [["PWR3", "1"], ["C3", "1"], ["R1", "2"], ["J2", "1"],
                                     ["U1", "1"], ["U1", "10"], ["U1", "22"], ["U1", "33"],
                                     ["U1", "42"], ["U1", "43"], ["U1", "44"], ["U1", "48"],
                                     ["U1", "49"]], "label": "3V3"},
            {"name": "1V1", "pins": [["U1", "23"], ["U1", "45"], ["U1", "50"]], "label": "1V1"},
            {"name": "0", "pins": [["PWRG", "1"], ["C1", "2"], ["C2", "2"], ["C3", "2"],
                                   ["J2", "4"], ["U1", "19"], ["U1", "57"],
                                   ["Y1", "2"], ["Y1", "4"]], "label": "0"},
            {"name": "XIN", "pins": [["U1", "20"], ["Y1", "1"]], "label": "XIN"},
            {"name": "XOUT", "pins": [["U1", "21"], ["Y1", "3"]], "label": "XOUT"},
            {"name": "SWCLK", "pins": [["U1", "24"], ["J2", "3"]]},
            {"name": "SWD", "pins": [["U1", "25"], ["J2", "2"]]},
            {"name": "USB_DM", "pins": [["U1", "46"]], "label": "USB_DM"},
            {"name": "USB_DP", "pins": [["U1", "47"]], "label": "USB_DP"},
            {"name": "FLASH_CS", "pins": [["U1", "56"]], "label": "FLASH_CS"},
            {"name": "FLASH_SCLK", "pins": [["U1", "52"]], "label": "FLASH_SCLK"},
            {"name": "FLASH_SD0", "pins": [["U1", "53"]], "label": "FLASH_SD0"},
            {"name": "FLASH_SD1", "pins": [["U1", "55"]], "label": "FLASH_SD1"},
            {"name": "R1", "pins": [["U1", "2"]]},
            {"name": "R2", "pins": [["U1", "3"]]},
            {"name": "R3", "pins": [["U1", "4"]]},
            {"name": "C1", "pins": [["U1", "5"]]},
            {"name": "C2", "pins": [["U1", "6"]]},
            {"name": "C3", "pins": [["U1", "7"]]},
            {"name": "C4", "pins": [["U1", "8"]]},
            {"name": "C5", "pins": [["U1", "9"]]},
        ],
        # 显式布局：U1 居中，3V3 顶轨/PWR3、GND 底轨/PWRG，外设避开电源引脚
        # stub 通道（Y1/J2/去耦电容在 U1 两侧/下方，避免 stub 穿外设本体短路）
        "layout": {
            "mode": "positions",
            "positions": {
                "U1": [80.0, 105.0, 0],
                "PWR3": [80.0, 25.0, 0],
                "PWRG": [80.0, 185.0, 0],
                "C1": [140.0, 60.0, 0],
                "C2": [140.0, 85.0, 0],
                "C3": [140.0, 110.0, 0],
                "Y1": [35.0, 165.0, 0],
                "J2": [140.0, 165.0, 0],
                "R1": [35.0, 130.0, 0],
            },
        },
        "default_label_type": "global",
        "keep_power_symbols": True,
        "no_connect_marks": True,
        "clear": True, "run_erc": True, "render": True,
    }


async def call(session, name, args) -> str:
    res = await session.call_tool(name, args)
    return "\n".join(getattr(c, "text", str(c)) for c in res.content)


async def redraw_main_manual(session) -> str:
    """main 页：符号放置 + 标签用 draw_circuit(route=false)，然后手动物理电源
    轨道（3V3 顶轨 / GND 底轨，IEC 61082 电源上地在下），信号网 auto_route。
    57 脚 MCU 页的电源轨道用物理总线是行业惯例，auto-trunk 在密集页易碰撞。
    """
    from kicad_mcp.tools.schematic import _read_symbols
    j = main_json()
    j["route"] = False
    j["run_erc"] = False
    out = [await call(session, "kicad_sch_draw_circuit",
                      {"circuit_json": json.dumps(j)})]
    syms = _read_symbols()

    def pin(ref, num):
        # 精确引脚坐标（注意：读回可能差 1 IU，吸附会让 stub 起点离开引脚→不连）
        ix, iy = syms[ref]["pins"][str(num)]
        return ix / MM, iy / MM

    async def wire(ax, ay, bx, by):
        # 两端都吸附网格（引脚本身就在 1.27 网格上，吸附不会移动）；
        # 只吸附一端会让 trunk 变斜线、stub 接不上。
        return await call(session, "kicad_sch_add_line",
                          {"x1_mm": _g(ax), "y1_mm": _g(ay),
                           "x2_mm": _g(bx), "y2_mm": _g(by)})

    async def rail(net, pins, y_rail):
        """画一条水平轨道 y_rail，每个引脚竖直 stub 接到轨道。"""
        xs = []
        n_stub = 0
        for (ref, num) in pins:
            px, py = pin(ref, num)
            xs.append(_g(px))
            if abs(py - y_rail) > 0.01:
                r = await wire(px, py, px, y_rail)
                n_stub += 1
        r2 = await wire(min(xs), y_rail, max(xs), y_rail)
        r3 = await call(session, "kicad_sch_add_label",
                        {"label_type": "global", "text": net,
                         "x_mm": _g(min(xs)), "y_mm": _g(y_rail)})
        out.append(f"  · 轨道 {net} @y={y_rail}: {n_stub} stub + 1 trunk + 1 标签"
                   f"\n      {r2[:60]}")

    # 3V3 顶轨（PWR3 在 (80,25.4) 处）
    vcc3 = [("PWR3", 1), ("U1", 1), ("U1", 10), ("U1", 22), ("U1", 33),
            ("U1", 42), ("U1", 43), ("U1", 44), ("U1", 48), ("U1", 49),
            ("C1", 1), ("C2", 1), ("C3", 1), ("R1", 2), ("J2", 1)]
    await rail("3V3", vcc3, 25.4)
    # GND 底轨（PWRG 在 (80,185.4) 处）
    gnd = [("PWRG", 1), ("U1", 57), ("U1", 19), ("Y1", 2), ("Y1", 4),
           ("J2", 4), ("C1", 2), ("C2", 2), ("C3", 2)]
    await rail("0", gnd, 185.4)
    # 1V1（DVDD 23/50 + VREG_VOUT 45）
    v11 = [("U1", 23), ("U1", 50), ("U1", 45)]
    await rail("1V1", v11, 168.0)
    # 信号网（XIN/XOUT/SWCLK/SWD）交给 auto_route
    sig = [{"name": "XIN", "pins": [["U1", "20"], ["Y1", "1"]]},
           {"name": "XOUT", "pins": [["U1", "21"], ["Y1", "3"]]},
           {"name": "SWCLK", "pins": [["U1", "24"], ["J2", "3"]]},
           {"name": "SWD", "pins": [["U1", "25"], ["J2", "2"]]}]
    out.append(await call(session, "kicad_sch_auto_route",
                          {"nets_json": json.dumps(sig)}))
    return "\n".join(out)


async def redraw_matrix(session) -> str:
    """矩阵页：15 键 3×5，每键每侧一个全局标签（Cx 列 / Rx 行）。

    走 kicad_sch_draw_circuit 的 label_only：同侧两脚自动短接、标签放外侧
    stub（不压符号）。键半宽 6.35 + stub，间距取 20.32mm（16 格）保证相邻
    标签互不碰撞。
    """
    # 键: K1..K15, 行 R1={1..5} R2={6..10} R3={11..15}, 列 Cx = {Kx, Kx+5, Kx+10}
    col_of = {k: f"C{((k - 1) % 5) + 1}" for k in range(1, 16)}
    row_of = {k: f"R{(k - 1) // 5 + 1}" for k in range(1, 16)}
    x0, y0, dx, dy = 60.0, 100.0, 20.32, 20.32
    symbols = []
    positions = {}
    for k in range(1, 16):
        r = (k - 1) // 5      # 0..2
        c = (k - 1) % 5       # 0..4
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
    j = {
        "symbols": symbols,
        "nets": nets,
        "layout": {"mode": "positions", "positions": positions},
        "default_label_type": "global",
        "clear": True, "run_erc": True, "render": True,
    }
    res = await call(session, "kicad_sch_draw_circuit",
                     {"circuit_json": json.dumps(j)})
    return res


def matrix_json():
    """矩阵页电路 spec（供 golden 回归复用；run_erc/render 由调用方覆盖）。"""
    col_of = {k: f"C{((k - 1) % 5) + 1}" for k in range(1, 16)}
    row_of = {k: f"R{(k - 1) // 5 + 1}" for k in range(1, 16)}
    x0, y0, dx, dy = 60.0, 100.0, 20.32, 20.32
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
