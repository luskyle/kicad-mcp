#!/usr/bin/env python3
"""重绘 keyboard_main.kicad_sch (v2, IU 精确连线)。

- RP2040 居中; 顶部物理 VDD 总线 + power:+3V3/GND 电源符号
- 底部晶振 + 负载电容 + 复位 (L 型走线, 端点取引脚原始 IU)
- USB/QSPI/SWD net label (wire 从引脚端引出)
- 所有未连引脚放置 no_connect (精确 IU)
"""
import sys
sys.path.insert(0, "src")

from kicad_mcp.client import KiCadClient
from kicad_mcp.tools.schematic import _sch_context
from kicad_mcp.proto.schematic import schematic_types_pb2 as st
from kicad_mcp.proto.common.types import base_types_pb2 as bt, enums_pb2 as en

MM = 10_000


def sym(lib, name, ref, x_mm, y_mm, value=None):
    s = st.Symbol()
    s.lib_id.library_nickname = lib
    s.lib_id.entry_name = name
    s.position.x_nm = round(x_mm * MM); s.position.y_nm = round(y_mm * MM)
    f1 = s.fields.add(); f1.name = "Reference"; f1.value = ref
    f2 = s.fields.add(); f2.name = "Value"; f2.value = value or name
    return s


def shape(rect, w=0.3):
    sh = st.Shape()
    sh.stroke_width = round(w * MM); sh.layer = st.SL_NOTES
    r = sh.graphic.rectangle
    r.top_left.x_nm = round(rect[0] * MM); r.top_left.y_nm = round(rect[1] * MM)
    r.bottom_right.x_nm = round(rect[2] * MM); r.bottom_right.y_nm = round(rect[3] * MM)
    sh.graphic.attributes.stroke.width.value_nm = round(w * MM)
    sh.graphic.attributes.stroke.style = en.SLS_SOLID
    sh.graphic.attributes.fill.fill_type = bt.GFT_UNFILLED
    return sh


def wire_i(x1, y1, x2, y2):
    """连线, 参数为 IU 整数"""
    ln = st.Line()
    ln.start.x_nm = int(x1); ln.start.y_nm = int(y1)
    ln.end.x_nm = int(x2); ln.end.y_nm = int(y2)
    ln.layer = st.SL_WIRE
    return ln


def label_i(text, x, y):
    lab = st.LocalLabel()
    lab.text.text.text = text
    lab.position.x_nm = int(x); lab.position.y_nm = int(y)
    return lab


def nc_i(x, y):
    n = st.NoConnect()
    n.position.x_nm = int(x); n.position.y_nm = int(y)
    return n


def text(t, x_mm, y_mm, h=2.5):
    tt = st.Text()
    tt.text.position.x_nm = round(x_mm * MM); tt.text.position.y_nm = round(y_mm * MM)
    tt.text.attributes.size.x_nm = round(h * MM); tt.text.attributes.size.y_nm = round(h * MM)
    tt.text.text = t
    return tt


def read_symbols(kc, header):
    """读所有符号的引脚绝对位置。
    返回 {ref: {"lib", "pos", "pins"(去重 dict), "raw"(全部引脚列表)}}
    """
    got = kc.get_items(header, [en.KOT_SCH_SYMBOL])
    syms = {}
    for a in got.items:
        s = st.Symbol(); a.Unpack(s)
        f = {x.name: x.value for x in s.fields}
        ref = f.get("Reference", "?")
        pins = {}
        raw = []
        for p in s.pins:
            key = p.name or p.number
            pins[key] = (p.position.x_nm, p.position.y_nm)
            raw.append((p.name, p.number, p.position.x_nm, p.position.y_nm))
        syms[ref] = {"lib": f"{s.lib_id.library_nickname}:{s.lib_id.entry_name}",
                     "pos": (s.position.x_nm, s.position.y_nm),
                     "pins": pins, "raw": raw}
    return syms


url, header = _sch_context()
print("connected:", url)

with KiCadClient(url, client_name="main2") as kc:
    # ===== 清空 (含全局标签等所有类型) =====
    got = kc.get_items(header, [en.KOT_SCH_SYMBOL, en.KOT_SCH_TEXT, en.KOT_SCH_LINE,
                                en.KOT_SCH_LABEL, en.KOT_SCH_GLOBAL_LABEL,
                                en.KOT_SCH_NO_CONNECT, en.KOT_SCH_SHAPE])
    ids = []
    for a in got.items:
        for cls in (st.Symbol, st.Text, st.Line, st.LocalLabel, st.GlobalLabel,
                    st.NoConnect, st.Shape):
            if a.Is(cls.DESCRIPTOR):
                m = cls(); a.Unpack(m); ids.append(m.id.value); break
    if ids:
        resp = kc.delete_items(header, ids)
        print(f"清空: {sum(1 for r in resp.deleted_items if r.status==1)}/{len(ids)}")

    # ===== 框 + 标题 =====
    kc.create_items(header, [
        shape((45, 50, 360, 255), 0.4),
        text("KEYBOARD 89 - 主控 MCU (RP2040)", 200, 38, 4.5),
        text("时钟 / 电源 / 复位 / 调试 · GPIO 与矩阵连接见各页", 200, 52, 2.2),
    ])

    # ===== 符号 =====
    aux = [
        sym("keyboard-89_local", "RP2040", "U1", 200, 150, "RP2040"),
        sym("power", "+3V3", "PWR3", 150, 82),          # 电源端口 (全局)
        sym("power", "GND", "PWRG", 260, 82),           # GND 端口 (全局)
        sym("Device", "C", "C3", 245, 78, "100nF"),     # 去耦
        sym("keyboard-89_local", "YXC", "Y1", 184.8, 212, "12MHz"),
        sym("Device", "C", "C1", 187.3, 203, "12pF"),   # XIN 负载
        sym("Device", "C", "C2", 182.2, 203, "12pF"),   # XOUT 负载
        sym("Device", "R", "R1", 207.5, 205, "10k"),    # 复位上拉
        sym("keyboard-89_local", "PIN-5P", "J2", 60, 220, "SWD"),
    ]
    resp = kc.create_items(header, aux)
    print(f"符号: {len(aux)} ok={sum(1 for c in resp.created_items if c.status.code==1)}")

    # ===== 读引脚 =====
    S = read_symbols(kc, header)
    u1 = S["U1"]["pins"]
    y1 = S["Y1"]["pins"]
    c1 = S["C1"]["pins"]; c2 = S["C2"]["pins"]; c3 = S["C3"]["pins"]
    r1 = S["R1"]["pins"]
    pwr3 = S["PWR3"]["pins"]; pwrg = S["PWRG"]["pins"]

    # ===== 顶部电源: 每电源脚放同名 +3V3 net label =====
    # (比物理总线更可靠: label 同名即同网络, 不受坐标精度影响)
    u1raw = S["U1"]["raw"]
    vdd_all = [(x, y) for (nm, num, x, y) in u1raw
               if nm in ("IOVDD", "DVDD", "ADC_AVDD", "USB_VDD", "VREG_VIN")]
    wires = []
    for px, py in vdd_all:
        wires.append(wire_i(px, py, px, py - 3 * MM))
        wires.append(label_i("+3V3", px, py - 3 * MM))
    # +3V3 电源端口
    pp = list(pwr3.values())[0]
    wires.append(wire_i(pp[0], pp[1], pp[0], pp[1] - 3 * MM))
    wires.append(label_i("+3V3", pp[0], pp[1] - 3 * MM))
    # 去耦 C3 pin1 -> +3V3, pin2 -> GND
    c3p1 = c3["1"]; c3p2 = c3["2"]
    wires.append(wire_i(c3p1[0], c3p1[1], c3p1[0], c3p1[1] - 3 * MM))
    wires.append(label_i("+3V3", c3p1[0], c3p1[1] - 3 * MM))
    wires.append(wire_i(c3p2[0], c3p2[1], c3p2[0], c3p2[1] - 3 * MM))
    # GND 电源端口
    gp = list(pwrg.values())[0]
    wires.append(wire_i(gp[0], gp[1], gp[0], gp[1] + 3 * MM))
    # RP2040 GND 脚
    gnd_pins = [(x, y) for (nm, num, x, y) in u1raw if nm == "GND"]
    for gx, gy in gnd_pins:
        wires.append(wire_i(gx, gy, gx, gy + 3 * MM))   # 底部 GND 脚引出

    # ===== 底部: 晶振 + 负载电容 =====
    xin = u1["XIN"]; xout = u1["XOUT"]
    # 时钟网络: XIN/XOUT + 晶振 + 负载电容 全用同名 label 连接
    osc1 = y1["OSC1"]; osc2 = y1["OSC2"]
    y1gnds = [(x, y) for (nm, num, x, y) in S["Y1"]["raw"] if nm == "GND"]
    c1p1 = c1["1"]; c1p2 = c1["2"]
    c2p1 = c2["1"]; c2p2 = c2["2"]
    # XIN 网络: XIN 脚 + C1 pin1 + Y1 OSC2
    for (px, py) in [xin, c1p1, osc2]:
        wires.append(wire_i(px, py, px, py + 3 * MM))
        wires.append(label_i("XIN", px, py + 3 * MM))
    # XOUT 网络: XOUT 脚 + C2 pin1 + Y1 OSC1
    for (px, py) in [xout, c2p1, osc1]:
        wires.append(wire_i(px, py, px, py + 3 * MM))
        wires.append(label_i("XOUT", px, py + 3 * MM))
    # GND: C1/C2 pin2 + Y1 GND 脚
    for (px, py) in [c1p2, c2p2] + y1gnds:
        wires.append(wire_i(px, py, px, py + 3 * MM))
        wires.append(label_i("GND", px, py + 3 * MM))

    # ===== 复位 R1 =====
    run = u1["RUN"]
    r1p1 = r1["1"]; r1p2 = r1["2"]
    # RUN -> R1 pin1 (竖线)
    wires.append(wire_i(run[0], run[1], r1p1[0], r1p1[1]))
    wires.append(wire_i(r1p2[0], r1p2[1], r1p2[0], r1p2[1] - 3 * MM))  # R1 上端 -> +3V3 label

    # ===== net label: USB / QSPI / SWD =====
    lw = []
    for n, lab in [("USB_DP", "USB_DP"), ("USB_DM", "USB_DM"),
                   ("QSPI_CSn", "FLASH_CS"), ("QSPI_SCLK", "FLASH_SCLK"),
                   ("QSPI_SD0", "FLASH_SD0"), ("QSPI_SD1", "FLASH_SD1")]:
        if n in u1:
            px, py = u1[n]
            lw.append(wire_i(px, py, px + 4 * MM, py))
            lw.append(label_i(lab, px + 4 * MM, py))
    # SWD/SWCLK -> 短竖线 + 同名 label (与 J2 相连)
    for n in ("SWD", "SWCLK"):
        if n in u1:
            px, py = u1[n]
            wires.append(wire_i(px, py, px, py + 4 * MM))
            lw.append(label_i(n, px, py + 4 * MM))
    # J2 调试接口 (5 脚): pin1=+3V3 pin2=SWD pin3=SWCLK pin4=GND pin5=NC
    j2 = S["J2"]["pins"]
    for num, lab in [("1", "+3V3"), ("2", "SWD"), ("3", "SWCLK"), ("4", "GND")]:
        if num in j2:
            px, py = j2[num]
            wires.append(wire_i(px, py, px + 3 * MM, py))
            lw.append(label_i(lab, px + 3 * MM, py))
    if "5" in j2:
        px, py = j2["5"]
        ncs_j2 = nc_i(px, py)
        lw.append(ncs_j2)
    # Y1 晶振 GND 脚 -> GND label
    ygnd = y1.get("GND")
    if isinstance(ygnd, tuple):
        wires.append(wire_i(ygnd[0], ygnd[1], ygnd[0], ygnd[1] + 3 * MM))
        lw.append(label_i("GND", ygnd[0], ygnd[1] + 3 * MM))
    # GND label 网络: C3 地脚 + RP2040 GND 脚
    for (gx, gy) in [(c3p2[0], c3p2[1] - 3 * MM)]:
        lw.append(label_i("GND", gx, gy))
    for gx, gy in gnd_pins:
        lw.append(label_i("GND", gx, gy + 3 * MM))
    # VREG_VOUT -> GND (内部稳压去耦)
    if "VREG_VOUT" in u1:
        px, py = u1["VREG_VOUT"]
        wires.append(wire_i(px, py, px, py + 3 * MM))
        lw.append(label_i("GND", px, py + 3 * MM))
    # TESTEN -> GND (测试使能接地)
    if "TESTEN" in u1:
        px, py = u1["TESTEN"]
        wires.append(wire_i(px, py, px, py + 3 * MM))
        lw.append(label_i("GND", px, py + 3 * MM))
    # 3V3 label 网络: R1 上端 (接 +3V3, 非 GND)
    lw.append(label_i("+3V3", r1p2[0], r1p2[1] - 3 * MM))
    resp = kc.create_items(header, wires + lw)
    print(f"连线+label: {len(wires)+len(lw)} ok={sum(1 for c in resp.created_items if c.status.code==1)}")

    # ===== no_connect: 所有未连引脚 =====
    connected = set()
    connected |= {"IOVDD", "DVDD", "ADC_AVDD", "USB_VDD", "VREG_VIN"}
    connected |= {"XIN", "XOUT", "RUN", "USB_DP", "USB_DM",
                  "QSPI_CSn", "QSPI_SCLK", "QSPI_SD0", "QSPI_SD1", "SWD", "SWCLK", "GND",
                  "VREG_VOUT", "TESTEN"}
    ncs = []
    for n, (px, py) in u1.items():
        if n in connected:
            continue
        ncs.append(nc_i(px, py))
    resp = kc.create_items(header, ncs)
    print(f"no_connect: {len(ncs)} ok={sum(1 for c in resp.created_items if c.status.code==1)}")

    # ===== 文字 =====
    kc.create_items(header, [
        text("时钟: 12MHz + 12pF×2 负载", 160, 232, 2.0),
        text("复位: R1 10k 上拉至 +3V3", 225, 230, 2.0),
        text("调试: J2 SWD (SWD/SWCLK/GND/+3V3)", 80, 240, 2.0),
        text("USB: USB_DP/DM → power 页", 300, 165, 2.0),
        text("QSPI: → flash 页 (GD25Q16E)", 300, 105, 2.0),
        text("矩阵 GPIO: 见 keyboard_matrix.sch", 200, 262, 2.0),
    ])

print("完成")
