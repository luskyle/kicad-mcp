#!/usr/bin/env python3
"""重绘 keyboard_main.kicad_sch: RP2040 最小系统专业布局。

- RP2040 居中, 顶部 VDD 电源总线 + 去耦电容
- 底部 晶振 + 负载电容 + 复位电路
- 左侧 GPIO 网络标签 (矩阵), 右侧 QSPI/USB 网络标签
- 未用引脚放置 no_connect X 标记
- 分区框 + 区域标题
"""
import sys
sys.path.insert(0, "src")

from kicad_mcp.client import KiCadClient
from kicad_mcp.tools.schematic import _sch_context
from kicad_mcp.proto.schematic import schematic_types_pb2 as st
from kicad_mcp.proto.common.types import base_types_pb2 as bt, enums_pb2 as en

MM = 10_000


def rnd(v):
    return round(v * MM)


def sym(lib, name, ref, x, y, value=None, orient=0):
    s = st.Symbol()
    s.lib_id.library_nickname = lib
    s.lib_id.entry_name = name
    s.position.x_nm = rnd(x); s.position.y_nm = rnd(y)
    s.orientation_degrees = orient
    f1 = s.fields.add(); f1.name = "Reference"; f1.value = ref
    f2 = s.fields.add(); f2.name = "Value"; f2.value = value or name
    return s


def shape(rect, w=0.3):
    sh = st.Shape()
    sh.stroke_width = round(w * MM); sh.layer = st.SL_NOTES
    r = sh.graphic.rectangle
    r.top_left.x_nm = rnd(rect[0]); r.top_left.y_nm = rnd(rect[1])
    r.bottom_right.x_nm = rnd(rect[2]); r.bottom_right.y_nm = rnd(rect[3])
    sh.graphic.attributes.stroke.width.value_nm = round(w * MM)
    sh.graphic.attributes.stroke.style = en.SLS_SOLID
    sh.graphic.attributes.fill.fill_type = bt.GFT_UNFILLED
    return sh


def wire(x1, y1, x2, y2):
    ln = st.Line()
    ln.start.x_nm = rnd(x1); ln.start.y_nm = rnd(y1)
    ln.end.x_nm = rnd(x2); ln.end.y_nm = rnd(y2)
    ln.layer = st.SL_WIRE
    return ln


def label(text, x, y):
    lab = st.LocalLabel()
    lab.text.text.text = text
    lab.position.x_nm = rnd(x); lab.position.y_nm = rnd(y)
    return lab


def noconnect(x, y):
    nc = st.NoConnect()
    nc.position.x_nm = rnd(x); nc.position.y_nm = rnd(y)
    return nc


def text(t, x, y, h=2.5):
    tt = st.Text()
    tt.text.position.x_nm = rnd(x); tt.text.position.y_nm = rnd(y)
    tt.text.attributes.size.x_nm = rnd(h); tt.text.attributes.size.y_nm = rnd(h)
    tt.text.text = t
    return tt


url, header = _sch_context()
print("connected:", url)

with KiCadClient(url, client_name="main") as kc:
    # ===== 清空 =====
    got = kc.get_items(header, [en.KOT_SCH_SYMBOL, en.KOT_SCH_TEXT, en.KOT_SCH_LINE,
                                en.KOT_SCH_LABEL, en.KOT_SCH_NO_CONNECT, en.KOT_SCH_SHAPE])
    ids = []
    for a in got.items:
        for cls in (st.Symbol, st.Text, st.Line, st.LocalLabel, st.NoConnect, st.Shape):
            if a.Is(cls.DESCRIPTOR):
                m = cls(); a.Unpack(m)
                ids.append(m.id.value)
                break
    if ids:
        resp = kc.delete_items(header, ids)
        print(f"清空: 删除 {sum(1 for r in resp.deleted_items if r.status==1)}/{len(ids)}")

    # ===== 1. 分区框 + 标题 =====
    items = [
        shape((45, 50, 360, 250), 0.4),   # MCU 核心区
        text("KEYBOARD 89 - 主控 MCU (RP2040)", 200, 38, 4.5),
        text("时钟 / 电源 / 复位 / 调试接口 · GPIO 连接见矩阵页", 200, 52, 2.2),
    ]
    resp = kc.create_items(header, items)
    print(f"框+标题: {len(items)} ok={sum(1 for c in resp.created_items if c.status.code==1)}")

    # ===== 2. RP2040 居中 =====
    resp = kc.create_items(header, [sym("keyboard-89_local", "RP2040", "U1", 200, 150, "RP2040")])
    print("RP2040:", resp.status, [c.status.code for c in resp.created_items])

    # 读 RP2040 引脚绝对位置
    got = kc.get_items(header, [en.KOT_SCH_SYMBOL])
    pins = {}
    for a in got.items:
        s = st.Symbol(); a.Unpack(s)
        if s.lib_id.entry_name == "RP2040":
            for p in s.pins:
                pins[p.name] = (p.position.x_nm / MM, p.position.y_nm / MM)
    # 关键引脚
    xin = pins.get("XIN"); xout = pins.get("XOUT")
    run = pins.get("RUN")
    vreg_vout = pins.get("VREG_VOUT"); adc_avdd = pins.get("ADC_AVDD")
    usb_dp = pins.get("USB_DP"); usb_dm = pins.get("USB_DM")
    swd = pins.get("SWD"); swclk = pins.get("SWCLK")
    print("关键引脚:", xin, xout, run, usb_dp, usb_dm, swd, swclk)

    # ===== 3. 辅助符号 =====
    aux = []
    # 晶振 (底部, 靠近 XIN/XOUT)
    yx = (xin[0] + xout[0]) / 2 if xin else 185
    yy = (xin[1] if xin else 195) + 8
    aux.append(sym("keyboard-89_local", "YXC", "Y1", yx, yy, "12MHz"))
    # 负载电容 C1/C2 (晶振两脚到地)
    if xin:
        aux.append(sym("Device", "C", "C1", xin[0], xin[1] + 6, "12pF"))
    if xout:
        aux.append(sym("Device", "C", "C2", xout[0], xout[1] + 6, "12pF"))
    # 复位电阻 R1 (RUN -> 3V3)
    if run:
        aux.append(sym("Device", "R", "R1", run[0] + 5, run[1] + 8, "10k"))
    # 顶部电源: +3V3 PWR_FLAG
    aux.append(sym("power", "PWR_FLAG", "PWR3", 200, 70, "+3V3"))
    # 去耦电容 C3 (3V3)
    aux.append(sym("Device", "C", "C3", 245, 75, "100nF"))
    # 调试接口 PIN-5P (SWD)
    aux.append(sym("keyboard-89_local", "PIN-5P", "J2", 60, 220, "SWD"))
    resp = kc.create_items(header, aux)
    print(f"辅助符号: {len(aux)} ok={sum(1 for c in resp.created_items if c.status.code==1)}")

    # ===== 4. 走线 =====
    wires = []
    # 顶部 VDD 总线: 一条水平 wire 覆盖 VDD 引脚排 (Y≈104.3)
    vdd_y = 104.3
    wires.append(wire(150, 78, 150, vdd_y - 15))       # +3V3 PWR 往下
    wires.append(wire(150, vdd_y - 15, 200, vdd_y - 15))  # 水平总线
    wires.append(wire(200, vdd_y - 15, 200, vdd_y))      # 连到 VDD 区
    wires.append(wire(200, vdd_y - 15, 245, vdd_y - 15)) # 到去耦电容
    # 晶振 -> XIN/XOUT
    if xin and xout:
        wires.append(wire(xin[0], xin[1], xin[0], xin[1] + 4))
        wires.append(wire(xout[0], xout[1], xout[0], xout[1] + 4))
        # 负载电容 -> GND
        wires.append(wire(xin[0], xin[1] + 4, xin[0], xin[1] + 7))
        wires.append(wire(xout[0], xout[1] + 4, xout[0], xout[1] + 7))
        # 晶振引脚 -> 短 wire
        wires.append(wire(yx - 2.54, yy - 1.75, yx - 2.54, xin[1] + 1))
        wires.append(wire(yx + 2.54, yy - 1.75, yx + 2.54, xout[1] + 1))
    # RUN -> R1 -> 3V3
    if run:
        wires.append(wire(run[0], run[1], run[0], run[1] + 4))
    resp = kc.create_items(header, wires)
    print(f"走线: {len(wires)} ok={sum(1 for c in resp.created_items if c.status.code==1)}")

    # ===== 5. net label (USB/QSPI/SWD/矩阵 GPIO) =====
    lw = []
    # USB
    if usb_dp and usb_dm:
        lw.append(wire(usb_dp[0], usb_dp[1], usb_dp[0] + 4, usb_dp[1]))
        lw.append(label("USB_DP", usb_dp[0] + 4, usb_dp[1]))
        lw.append(wire(usb_dm[0], usb_dm[1], usb_dm[0] + 4, usb_dm[1]))
        lw.append(label("USB_DM", usb_dm[0] + 4, usb_dm[1]))
    # 调试 SWD/SWCLK -> PIN-5P 方向
    if swd and swclk:
        lw.append(wire(swd[0], swd[1], swd[0], swd[1] + 6))
        lw.append(wire(swclk[0], swclk[1], swclk[0], swclk[1] + 6))
    # QSPI 到 Flash (右侧 net label)
    qspi = ["QSPI_CSn", "QSPI_SCLK", "QSPI_SD0", "QSPI_SD1"]
    for i, q in enumerate(qspi):
        if q in pins:
            px, py = pins[q]
            lw.append(wire(px, py, px + 4, py))
            lw.append(label("FLASH_" + q.replace("QSPI_", ""), px + 4, py))
    resp = kc.create_items(header, lw)
    print(f"net label: {len(lw)} ok={sum(1 for c in resp.created_items if c.status.code==1)}")

    # ===== 6. no_connect: 未连接的 GPIO =====
    connected = set()
    for n in ["XIN", "XOUT", "RUN", "USB_DP", "USB_DM", "SWD", "SWCLK",
              "QSPI_CSn", "QSPI_SCLK", "QSPI_SD0", "QSPI_SD1"]:
        connected.add(n)
    # 电源脚已连总线 (IOVDD/DVDD/ADC_AVDD/VREG_VIN/VREG_VOUT/USB_VDD)
    for n in pins:
        if n in ("IOVDD", "DVDD", "ADC_AVDD", "VREG_VIN", "VREG_VOUT", "USB_VDD", "GND"):
            connected.add(n)
    ncs = []
    for n, (px, py) in pins.items():
        if n in connected:
            continue
        ncs.append(noconnect(px, py))
    resp = kc.create_items(header, ncs)
    print(f"no_connect: {len(ncs)} ok={sum(1 for c in resp.created_items if c.status.code==1)}")

    # ===== 7. 文字标注 =====
    txt = [
        text("时钟区: 12MHz 晶振 + 负载电容", 185, 235, 2.0),
        text("调试: SWD / SWCLK", 85, 235, 2.0),
        text("USB: USB_DP / USB_DM → power 页", 300, 155, 2.0),
        text("QSPI: → flash 页 (GD25Q16E)", 300, 110, 2.0),
        text("矩阵 GPIO: 见 keyboard_matrix.sch (R1-R5/C1-C22)", 200, 262, 2.0),
    ]
    resp = kc.create_items(header, txt)
    print(f"文字: {len(txt)} ok={sum(1 for c in resp.created_items if c.status.code==1)}")

print("完成")
