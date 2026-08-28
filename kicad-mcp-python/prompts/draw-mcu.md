# 模板：画 MCU 主控页（大芯片）

> 典型：RP2040 等 57 脚 MCU + 晶振 + SWD + 去耦。
> 大芯片页用**显式布局 + 物理电源轨道 + 信号网 auto_route**，不用纯自动布局（会挤）。

## 步骤

1. **显式布局**（`layout.mode: "positions"`）：MCU 居中，电源符号在上下、外设避开引脚 stub 通道
   ```json
   "layout": {"mode": "positions", "positions": {
       "U1":   [80, 105, 0],
       "PWR3": [80, 25, 0],     // 3V3 顶轨
       "PWRG": [80, 185, 0],    // GND 底轨
       "C1": [140, 60, 0], "C2": [140, 85, 0], "C3": [140, 110, 0],
       "Y1": [35, 165, 0], "J2": [140, 165, 0], "R1": [35, 130, 0]
   }}
   ```

2. **电源拓扑按数据手册**（例 RP2040）：
   - IOVDD×6 / USB_VDD / ADC_AVDD / VREG_VIN → **3V3**
   - DVDD×2 / VREG_VOUT → **1V1**（内部 LDO 1.1V 核心电压，**不是 3V3**）
   - TESTEN / GND → 0
   - XIN/XOUT → 晶振；QSPI → flash（跨页）；SWCLK/SWD → SWD 排针

3. **一次调用 draw_circuit**（route 可先画符号+标签）：
   ```json
   { "symbols": [...], "nets": [...],
     "layout": {"mode": "positions", "positions": {...}},
     "default_label_type": "global", "keep_power_symbols": true,
     "no_connect_marks": true, "clear": true, "run_erc": true, "render": true }
   ```

4. **大芯片页电源轨道**（57 脚密集，auto-trunk 易碰撞）：
   用 `route: false` 画符号+标签后，手动画**物理水平轨道**（3V3 顶轨 / GND 底轨），
   每个电源引脚竖直 stub 接到轨道，轨道两端吸附 1.27mm 网格。

## 关键约定
- **已知限制**：RP2040 这类大芯片的引脚位置经 API 读回可能与 KiCad 连通性坐标不一致
  （`SCH_SYMBOL::Serialize::GetPosition` 问题），导线可能连不上引脚 → ERC "Pin not connected"。
  遇到先检查是不是该限制；GD25Q16E 等普通符号正常。
- 信号网（XIN/XOUT/SWCLK/SWD）交给 `kicad_sch_auto_route`。
- 外设（晶振/SWD/去耦）放在 MCU 两侧/下方，避开电源引脚 stub 通道（否则 stub 穿外设本体短路）。
