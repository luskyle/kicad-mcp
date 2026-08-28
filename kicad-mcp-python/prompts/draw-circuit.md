# 模板：画一个 XX 电路（通用）

> 用途：把"用户想画一个电路"翻译成一次 `kicad_sch_draw_circuit` 调用。
> 目标：一次调用画完并**交付即通过**（ERC 门禁自动跑，电源网络缺驱动会自动补 PWR_FLAG）。

## 步骤

1. **确认电路拓扑**（向用户要齐，缺的就用合理默认）：
   - 元件清单（类型/值/数量），例如电阻分压、LDO 电源、MCU 页、按键矩阵
   - 网络连接（哪些元件引脚连到一起）、网络命名
   - 是否需要跨页（多页工程 → `default_label_type: "global"`）

2. **构造 circuit_json**（一次调用 `kicad_sch_draw_circuit`）：
   ```json
   {
     "symbols": [
       {"ref": "R1", "lib": "Device", "symbol": "R", "value": "10k"},
       {"ref": "V1", "lib": "Simulation_SPICE", "symbol": "VDC", "value": "5", "orient": 90}
     ],
     "nets": [
       {"name": "VIN", "pins": [["V1","1"], ["R1","1"]]},
       {"name": "OUT", "pins": [["R1","2"], ["C1","1"]], "label": "OUT"}
     ],
     "layout": {"mode": "auto"},
     "clear": true, "run_erc": true, "render": true
   }
   ```

3. **约定（必须遵守）**：
   - 坐标/网格：所有符号中心在 **1.27mm 网格**（draw_circuit 自动吸附）
   - **标签默认 1.27mm** 字高（KiCad 标准），别改大
   - 电源网络（3V3/5V/VCC/VBUS）与 GND：自动放**顶部/底部轨道**（IEC 61082 电源上、地在下）
   - 含 IC（power_in 引脚）时设 **`keep_power_symbols: true`** 放 PWR_FLAG；
     不设时门禁会自动补 PWR_FLAG（放心）
   - 单引脚跨页网络（GPIO、FLASH_* 等）自动放同名标签；多页工程用 global
   - 未用引脚设 `no_connect_marks: true` 打 X

4. **读结果**：看 "ERC 门禁" 是否 PASS；若有 blocking 违规（Pin not connected 等），
   分析布线/连接并修正后重画。

## 检查清单（交付前）
- [ ] ERC 门禁 PASS（无 blocking）
- [ ] 标准审查无 ❌
- [ ] 每个符号有 Reference + Value
- [ ] 电源/关键网络有标签、GND 用 "0"
- [ ] 渲染 SVG 里没有标签压符号/导线、没有重叠
