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
     "sheet": {"title": "RC 电路", "revision": "1.0", "company": "xxx", "comment1": "..."},
     "clear": true, "run_erc": true, "render": true
   }
   ```

> **图纸信息（sheet）**：`sheet` 字段会自动填充右下角标题栏
> （Title / Date / Revision / Company / Comment1-4）；Date 不填则用当天日期。
> draw_circuit 还会自动把布局**居中到可用绘制区并避开右下角标题栏**（不会
> 再被元件/标签遮挡图纸信息）。

## 标签选型规则（重要）

原理图标签分几类，**AI 必须按网络性质选对类型、形状和方向**，不能一律用默认：

| 情况 | 标签类型 label_type | 说明 |
|---|---|---|
| 跨页面网络（多页工程） | `global` | 全局标签，跨页同名即相连 |
| 单页内部网络 | `local` | 本地标签 |
| 层次化设计（跨子图） | `hier` | 层次标签（配合层次图） |
| ERC/仿真/差分/PCB 指令 | `directive` | 指令标签（Net Flag） |

**连接箭头形状 shape（global/local/hier 用）**，按该网络的信号方向/驱动类型选：
- `output`：驱动/输出网络（电源输出、芯片输出、振荡器输出）
- `input`：输入网络（芯片输入、使能、复位输入）
- `bidirectional`：双向网络（数据线 D0-D7、SDA、GPIO 双向）
- `tri_state`：三态（总线、共享数据线）
- `unspecified`：无明确方向（无源网络、电阻网络中间节点）——KiCad 默认斜杠

**连接点方向 spin**：连接点（小旗/箭头根）应朝向导线所在方向。
导线在标签左侧 → `spin: "left"`；上方 → `"up"`；右侧 → `"right"`；下方 → `"down"`。

**指令标签形状 directive_shape（directive 用）**：
- `point`：电源/地 PWR_FLAG 风格
- `circle`：仿真指令（默认）、“不连接检查”
- `diamond`：差分对
- `rectangle`：自定义 PCB/净形状指令

## 自动连线（智能直连 + 布局）

draw_circuit 的自动布局与布线已做智能化处理，AI 通常无需干预：

- **布局串行同行**：同信号流的元件排在同一行（信号左→右），不再上下错行，
  连线更直、更紧凑。
- **元件自动朝向**：2 引脚元件（电阻/电容/二极管/电感等）在信号流水平串联时
  自动水平放置（orient 90），引脚朝左右 —— 无需手动指定 orient。用户显式指定
  orient 时优先。
- **两引脚网络智能直连**：相邻元件的连接引脚若同水平线/竖直线（或可用
  L 形两段），直接短接（1 段线），跳过 trunk（3 段 U 形绕线）。
  —— 串联电阻、RC、元件对会得到最直接的连线。
- **多引脚网络**（电源、IC 总线）仍走专业 trunk bus 风格（每网络独占水平
  道 + 垂直 stub + Junction）。
- **电源上/地在下轨道**：电源网络 trunk 走顶部/底部轨道（IEC 61082）。
- 标签 stub 长度自动按文字宽度调整（长网络名不压符号），右侧引脚同样处理。

推荐做法：对每条要打标签的网络先调用一次
`kicad_sch_recommend_label(net_name, pin_type, cross_page, purpose)` 拿到推荐值，
再把 `label_shape` / `label_spin` 写进该网络的 JSON，例如：
```json
{"name": "SCLK", "pins": [...], "label": "SCLK",
 "label_type": "global", "label_shape": "output", "label_spin": "left"}
```

## 旋转 / 镜像（布线时灵活运用）

原理图编辑器提供 顺时针旋转(R)、逆时针旋转(Shift+R)、水平镜像(X)、垂直镜像(Y)。
AI 布线/摆放时按需用 `kicad_sch_transform_item` 调整：
- **符号方向不对、引脚朝向挡住走线** → 旋转符号（cw/ccw）让引脚朝外、朝走线方向
- **符号左右/上下颠倒（对称符号）** → 镜像（x/y）
- **标签连接点方向与导线不符** → 旋转标签 spin，或镜像交换 left↔right / up↔down

调用前先用 `kicad_sch_get_items` 拿到目标元素 id，再变换。

## 约定（必须遵守）

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
- [ ] 标签类型/形状/方向符合上面的选型规则（跨页 global、驱动 output、双向 bidi…）
- [ ] 渲染 SVG 里没有标签压符号/导线、没有重叠
