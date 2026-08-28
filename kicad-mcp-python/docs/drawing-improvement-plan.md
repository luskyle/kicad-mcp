# kicad-mcp 做图能力提升方案（优化路线图）

> 状态：**已定稿，作为后续优化的唯一依据**。每次改进对照本方案的层级/优先级执行，
> 完成一项就更新对应条目的状态（`[x]`）并记录验证结果。
>
> 定稿日期：2026-08-28

## 1. 现状盘点

**原理图侧（`src/kicad_mcp/tools/schematic.py`，约 19 个工具，已很强）**
- 放置：`kicad_sch_add_text` / `add_line` / `add_symbol` / `add_label` / `add_shape` / `add_no_connect` / `add_image`
- 引脚感知：`add_symbol` 返回引脚、`kicad_sch_connect` 按 KiCad 计算的真实引脚坐标连线、自动避让
- 验证闭环：`kicad_sch_erc` / `kicad_sch_simulate` / `kicad_sch_simulate_gui` / `kicad_sch_detect_simulation`
- 布局辅助：`kicad_sch_get_sheet_info` / `kicad_sch_check_layout` / `kicad_sch_place_symbols_grid`

**PCB 侧（`src/kicad_mcp/tools/pcb.py`，只有 3 个工具，极弱）**
- `kicad_pcb_add_text` / `kicad_pcb_add_track` / `kicad_get_pcb_items`

**库侧（`symbol_browser.py` / `symbol_lib.py`）**
- `kicad_sch_list_libraries` / `kicad_sch_search_symbols` / `kicad_sch_create_custom_symbol`

## 2. 核心瓶颈

| 瓶颈 | 后果 |
|---|---|
| **盲绘**：MCP 是纯文本，AI 画完看不到结果，只能靠 get_items 反推 | 迭代效率极低，当前做图能力的最大天花板 |
| **PCB 覆盖不足**：proto 里 Footprint/Via/Zone/Arc/TextBox/Dimension 全有，Python 层只暴露 2 个创建工具 | PCB 基本画不了 |
| **低层原语多、高层"成图"少**：几十个"加一条线"式工具，缺少"根据规格画一整张图"的工具 | 大图要靠 LLM 自己编排几百次调用 |
| **布线只有启发式**：`_route_avoiding` 是试几条轨道，无网格搜索、无多网络全局布线 | 复杂电路绕不开障碍、交叉多 |
| **库/多页/层次化缺失**：自定义符号要重启 eeschema；API 不支持 Sheet 子图 | 中大型项目（多页、分层）画不了 |

## 3. 方案：四层实施（按 ROI 排序）

### L0 — 视觉闭环 ✅（2026-08-28 已完成）

> 目的：让 AI 画完"看得到"结果，所有后续层的迭代都因此变快。

- `kicad_sch_render(sch_file, out, include_svg, max_svg_chars, ...)`：用 `kicad-cli sch export svg`
  导出 **SVG 文本**直接作为工具返回值（SVG 是文本，LLM 可直接读坐标/接线关系），同时落盘供人查看。
- `kicad_pcb_render(pcb_file, out, format, layers, ...)`：`format=svg`（`pcb export svg --mode-single`，
  2D 分层矢量图，AI 可读）或 `format=png`（`pcb render`，3D 图，给人看）。
- `server.py` instructions 教导 AI 工作流：`画 → render 看 → 修正 → 再 render`。

**验收**：AI 从"我猜画对了"变成"看 SVG 确认接线正确"。
**实现文件**：`src/kicad_mcp/tools/render.py`（含跨域 CLI 环境辅助函数）。

### L1 — 补齐 PCB 做图（大部分纯 Python + 少量 C++ 验证）

> proto 已定义、C++ 序列化大部分已存在，只需在 `pcb.py` 暴露。

- [ ] `kicad_pcb_add_footprint(lib, entry, x, y, rot, ref, value)`（Footprint 需验证 `TypeNameFromAny` 是否已映射，没有就补一行）
- [ ] `kicad_pcb_add_via(x, y, net, size, drill)`、`kicad_pcb_add_arc`、`kicad_pcb_add_shape`（矩形/圆/文本在任意层）
- [ ] `kicad_pcb_add_zone(points, net, layer)`（铜区，含 `CopperZoneSettings`）
- [ ] `kicad_pcb_add_textbox`、`kicad_pcb_add_dimension`
- [ ] `kicad_pcb_route(from_pad, to_pad, layer, width)`：多段走线 + 自动过孔换层（复用 sch 避让思路的 PCB 版）
- [ ] `kicad_pcb_drc()` → `kicad-cli pcb drc`，作为 PCB 版 ERC 门禁

**验收**：PCB 从"只有文字和线"到"放得下元件、连得上网络、过 DRC"。

### L2 — 高层"成图"工具（纯 Python，把 `tests/redraw_*` / `draw_*` 收编）✅ 原理图部分已完成（2026-08-28）

> "做图"的最终形态：一次调用画一整张图。实现于 `src/kicad_mcp/tools/circuit.py`。

- [x] `kicad_sch_draw_circuit(circuit_json)`：一键成图 —— 解析电路描述（symbols + nets，
      nets[].pins 顺序隐含信号方向）→ 自动布局 → 布线 → 标签 → 保存 → ERC → 渲染 SVG。
      已验证：RC（ERC ✅ + SPICE 仿真 v(OUT) 0→4.966V τ≈0.1s）、分压（ERC ✅ + v(OUT)=3.333V）、
      平行电阻（ERC ✅）。**杀手级工具**。
- [x] `kicad_sch_auto_layout(symbols_json, nets_json)`：按连通图流向来排（stage BFS → 列，
      行号 zigzag 防共线合并；电源符号放上/下轨道），取代静态 `place_symbols_grid`。
- [x] `kicad_sch_auto_route(nets_json)`：批量自动布线 —— 每网络独立 trunk 道（used_lanes 隔离），
      引脚垂直 stub 接到 trunk，自动避让符号（排除自身包围盒）。已含 Junction。
- [ ] `kicad_pcb_place_footprints(symbols_json)`：原理图 → PCB 对应封装摆放骨架。（用户暂不急 PCB，延后）

**L2 关键踩坑（务必保留）**：
- **布局必须 zigzag 分行**（`y = y0 + (stage%2)*row_gap`）：所有符号同一行时，不同网络的水平导线
  落在同一 y 会被 KiCad 合并成一条贯穿线 → 整排短路。
- **导线端点落在另一条导线中部不会自动连接**（KiCad 规则）→ trunk 布线必须在每个 stub-trunk
  汇合点显式放 **Junction**（`schematic_types_pb2.Junction`，API 支持创建，已实测）。
- **电源符号（power:GND/+3V3，引脚是 power_in）需要 power_out 驱动**，否则 ERC 报
  "Input Power pin not driven"。draw_circuit 默认不放置电源符号，改用**本地标签**表示电源网络
  （ERC ✅ 且 SPICE netlist 干净）；GND/0 网络标签文本用 **"0"**（SPICE 地），仿真才正确。
- 电源符号参与流向计算会成环（都连到地/电源）→ `_flow_stages` 跳过含电源符号的网络；
  布局时用完整符号列表算 stage、但只放置非电源符号。
- trunk 道必须吸附到 1.27mm 网格（否则 ERC 报 "Symbol pin or wire end off connection grid"）。
- `_symbol_bbox_mm` 的 3.81mm padding 会让引脚自身 stub 被误判穿过本体 → stub 避让时
  排除所属符号自身包围盒（`owner_bbox_map`）。
**L2 增强（2026-08-28，按行业标准约束）**：
- **行业标准**: 原理图布局遵循 **IEC 61082-1**（信号流左→右、电源上/地在下、少交叉、
  Junction 明确连接点）+ IEEE 315 / IEC 60617（符号外形，由库保证）+ IPC-2612（位号/值齐全）。
  详见 `docs/schematic-standards.md`（标准号 → 代码落点映射表）。
- [x] `_barycenter_order`：列内按邻居平均行序排序（Sugiyama barycenter），减少连线交叉。
- [x] `_power_rail_lanes`：电源网络 trunk 放**底部轨道**（GND/0）或**顶部轨道**（VCC/3V3），
      符合"电源上、地在下"惯例（`_route_net_trunk` 新增 `preferred_lane` 参数）。
- [x] `no_connect_marks` 选项：网表里没出现的未用引脚自动打 **NoConnect(X)**，ERC 干净且规范。
- 验证：RC（ERC✅+仿真✅）、分压（ERC✅）、平行（ERC✅）、未用引脚 X（ERC✅）。

### L2.5 — 标准成为 MCP 常驻能力 ✅（2026-08-28）

> 回答"行业标准能否作为 MCP 功能参与每个设计"：**能**。标准不只是文档，
> 而是 MCP 的**常驻审查能力**，四条通道同时参与：

- [x] **`kicad_sch_standards_check`**（新工具，`tools/standards.py`）：对任意原理图跑
      IEC 61082-1 / IPC-2612 质量清单 → ✅/⚠️/❌ + 修复建议。
      检查项：位号值齐全 / 引脚 1.27mm 网格 / 无符号重叠 / 不越界 / 导线交叉数 /
      电源上-地在下 / 网络标签命名 / ERC。已实测能抓到离网格违规。
- [x] **`draw_circuit` 每次绘制后自动跑标准审查**（`standards_check` 选项，默认 true）。
- [x] **标准作为硬约束内建于成图算法**：信号流左→右、电源轨道上/下、Junction、1.27mm 网格、
      Reference/Value、NoConnect —— 画出来就合规。
- [x] **server.py instructions 内置 7 条设计规范**，引导 AI 每次设计遵守。

**验证**：RC 自动审查 7 通过/0 不合规；独立工具 8 项全通过；负向测试（离网格符号）能抓到 ⚠️。
### L3 — 原理图补强（Bus + 阵列 已完成 ✅，Sheet/库热更新 暂缓）

- [x] **Bus 支持** ✅（2026-08-28）：`tools/bus.py` 新增 `kicad_sch_add_bus`（总线导线，
      自动吸附网格）/ `kicad_sch_add_bus_label` / `kicad_sch_add_bus_entry`（**BusEntry**，
      C++ patch）/ `kicad_sch_connect_bus`（一键把引脚连到水平总线，自动 entry + 竖直导线 +
      可选 signal 成员标签）。
- [x] **阵列** ✅：`kicad_sch_array(symbols_json, nx, ny, dx, dy)` 网格重复放置、位号自动编号。
- [ ] **Sheet 子图（多页）**：暂缓 —— SCH_SHEET 创建/路径/实例较复杂，且现有多页工程
      （键盘 4 页）已用多文件 + 全局标签方案，够用。
- [ ] **库热更新**：暂缓 —— C++ 尝试过 `LIBRARY_MANAGER` 刷新（`GlobalTablesChanged` +
      注入 sym-lib-table 行），但会触发 eeschema 主线程 ~100% CPU 忙循环（异步库加载器）。
      `kicad_sch_reload_libraries` 已保留为安全无操作（诚实提示"重启 eeschema"）。

**L3 C++ patch（已编译进 eeschema）**：
- **BusEntry**：`schematic_types.proto` 加 `BusEntry{id,position,end}` +
  `SCH_BUS_ENTRY_BASE::Serialize/Deserialize`（sch_bus_entry.cpp，m_pos=总线侧、GetEnd=导线侧）+
  `TypeNameFromAny` 映射 `BusEntry→SCH_BUS_WIRE_ENTRY_T` + GetItems serializableTypes 加 bus entry。
- **ReloadLibraries**：proto 命令 + handler 注册（当前安全 no-op）。
- `gen_proto.sh` 重生成 Python pb；`ninja eeschema` 重编译。

**L3 关键踩坑（务必保留）**：
- **总线/导线/entry 必须全部在 1.27mm 网格**，否则 ERC 报 off-grid 且不连接。
- **总线必须有名字**：bus label 必须落在总线上（add_bus_label 自动吸附网格）。
- **信号线连总线要有成员标签**（signal=，如总线 `D[0..2]` 的成员 `D0`），否则 ERC 报
  "graphically connected to bus but not a member" 且引脚显示未连接。
- `kicad_sch_connect_bus` 的 bus_y 自动吸附网格；entry 偏移保持 1.27 整数倍。
- `_clear_sheet` 已扩展为能清 BusEntry（KOT_SCH_BUS_WIRE_ENTRY/BUS_BUS_ENTRY）。
- **bus entry 语义**：`at`(m_pos) 落在总线上、`GetEnd`(pos+size) 接导线（对照官方
  qa/data/eeschema/issue19646/Resolver.kicad_sch 验证）。

### keyboard-89 重绘验证（2026-08-28）—— 用新工具重画 4 页 + 逐页验证

**结果**：flash ✅ / power ✅ / matrix ✅ / main ⚠️（RP2040 引脚 API 连接 bug，见下）。

| 页 | 工具 | 验证 |
|---|---|---|
| flash | draw_circuit（keep_power+轨道） | ERC 只剩跨页"not driven"（FLASH_* 由 main 驱动）✅ |
| power | draw_circuit（横排+轨道） | ERC **0 error**（只剩 USB_DM/DP 跨页 label）✅ |
| matrix | 网格放置 15 键 + 全局标签 | ERC **无违规** ✅ |
| main | 显式布局 + 物理电源轨道 + auto_route | ⚠️ RP2040 引脚无法 API 连接（见下） |

**跨页一致性 ✅**：4 页全局标签（`3V3`/`0`/`FLASH_*`/`USB_DM|DP`/`C1..C5`/`R1..R3`）全部匹配。

**本轮对 draw_circuit/auto_route 的算法修复（已编入 circuit.py）**：
1. 多引脚同列 → 用 **collector**（竖直收集线 + 水平 stub），不用简单竖直 stub
   （会共线合并、中段引脚连不上、且穿过列内其他网络的引脚 → 短路）。
2. trunk/stub 必须避开**其他网络的引脚**（`_foreign_pins` 精确避让）。
3. bbox 检查用**本体包围盒**（收缩 2.54mm），3.81mm padding 误挡干净通道。
4. 兜底 lane 吸附 1.27mm 网格（否则 off-grid）。
5. `_power_rail_lanes` 单位 bug（y_mm 已是 mm）；keep_power 用 rail_refs 让 3V3 顶轨/0 底轨。
6. 手动画轨道 wire 两端都吸附网格。
7. draw_circuit 新增：`label_type`（global 跨页）、`keep_power_symbols`、`label_only`
   （矩阵类不拉线只放标签）、`layout.positions`（显式布局）、`route:false`（只放符号+标签）。

**已知限制：RP2040 引脚 API 连接 bug**——导线精确落在 `_read_symbols` 报告的引脚位置
（含 Junction、换候选位置）仍报 "Pin not connected"，而 GD25Q16E 等其他符号正常。
疑似 C++ `SCH_SYMBOL::Serialize` 的 `GetPosition()` 返回图形位置，与 KiCad 连通性用的
位置不一致。**待 C++ 侧修复（暂缓）**；main 页其余部分（布局/标签/轨道/信号网）已画好。

### 标签尺寸与摆放修复（2026-08-28）—— 用户反馈"标签的尺寸与摆放一直是问题"

**根因**：默认字高 2.54mm（KiCad 标准 1.27 的两倍），且标签直接放在引脚位置、叠在符号上
（矩阵页同侧两脚各放一个重复标签 → 文字互相压）。

**工具层修复（`circuit.py`/`schematic.py`）**：
1. **尺寸**：标签默认字高 → **1.27mm**（KiCad 标准）；`label_size_mm`（整图）/
   `nets[].label_size_mm`（单网）可覆盖。
2. **摆放规则**：
   - trunk 标签 → 放 trunk **左端外侧 2.54mm 引出段（tab）**上，避开第一条竖直 stub；
   - 无 trunk 的标签（单引脚跨页 / label_only）→ 放**引脚外侧短 stub** 上（stub 长度按
     文本宽度自适应 `max(2.54, len*size*0.62+1.27)` 并吸附 1.27 网格），文字落在 stub
     上、不压符号本体（尤其左侧引脚）；
   - label_only（矩阵）→ 按（符号,网络）分组：同侧同网多引脚先短导线短接，只放
     **一个**标签（矩阵开关每侧 2 脚同网，标签 60→30 去重）。
3. **外侧方向**由 `_pin_outward_dir`（引脚相对符号中心）判定，不依赖库旋转矩阵。

**验证**：flash(6)/power(5)/matrix(30)/main(22) 标签互相重叠 **0**；flash/power/matrix
标签压符号本体 **0**（距最近引脚 ≥0.97mm）；matrix ERC **无违规**；flash/power ERC 与
之前一致（仅跨页 label 警告 + 封装库警告）。main 页 5 处标签仍压 RP2040 本体 = 已知
RP2040 引脚读回 bug 的连带（引脚位置都偏，标签跟随）。

### L4 — 质量与工程化（已完成 ✅ 2026-08-28，工具共 44）

- [x] **DRC/ERC 门禁** ✅：`tools/quality.py` 新增 `kicad_sch_erc_gate`
  - 结构化解析 KiCad 官方 ERC（severity/描述/位置），违规分三类：
    **blocking**（Pin/Wire/Label not connected、off-grid、短路、电源未驱动，必须 0）/
    **benign**（跨页输入未驱动、Label 只连一引脚、封装库缺失，豁免）/ warning。
  - **自动修复**：netlist 检测含 power_in 但无 power_out 的电源网络 → 自动补
    `power:PWR_FLAG` 并接线 → 重跑，最多 max_attempts 轮 → PASS/FAIL。
    （LDO 输出驱动的 3V3 无 power_in 不会误加 —— 避免"电源输出和电源输出已连接"。）
  - draw_circuit 集成：`run_erc` 时走门禁（取代裸 ERC 文本），交付即通过。
  - 验证：无 PWR_FLAG 的最小 IC 电路自动补 2 个 PWR_FLAG 后 PASS；键盘
    flash/power/matrix 门禁全 PASS（0 blocking）。
- [x] **Golden 回归测试** ✅：`kicad_mcp/golden.py` + `tests/golden/*.golden.json` +
  `tests/run_golden.py`
  - 判据 = **netlist 网络连通性**（每个网络的 (ref,pin) 节点集合）+ 标签集合
    —— 比坐标/像素稳（布局/绕线变化不影响电气正确性）。
  - 已存 5 个基线：rc / divider / flash / power / matrix。
  - `run_golden.py`：重画 + 对比（重画能抓工具回归）；`--gen` 重新生成基线。
  - **负向验证**：篡改 golden 期望节点 → 回归 FAIL（0/1），能抓到电气回归 ✅。
  - 注意：KiCad 文件里 local label 是 `(label ".."` 不是 `(local_label`。
- [x] **prompt 模板库** ✅：`prompts/*.md` + `tools/prompts.py`
  - `kicad_get_prompt_template(name)` / `kicad_list_prompt_templates()`。
  - 模板：draw-circuit（通用）/ draw-power（USBC/LDO）/ draw-mcu（大芯片）/
    draw-matrix（label_only 矩阵）/ verify-simulate（门禁+标准+仿真+golden）。
  - 每个模板含 circuit_json 例子、关键约定（踩坑）、交付检查清单。

## 4. 落地顺序与理由

```
L0(视觉) ──▶ L1(PCB) ──▶ L2(成图工具) ──▶ L3(原理图补强) ──▶ L4(工程化)
 已完成       2~3天          3~5天             1~2周            持续
```

L0 先做，因为它让后面所有层的迭代都变快（每个新工具都能立刻"看图验证"）；
L1/L2 纯 Python、风险低、收益大；L3 才动 C++ 编译，放后面按需做。

## 5. 约束与注意（来自踩坑记录）

- 原理图坐标 1mm = **1e4** IU；PCB 1mm = 1e6 nm（`SCH_IU_PER_MM` vs `PCB_IU_PER_MM`）。
- 浮点坐标必须 `round(x*MM)` 而不是 `int(x*MM)`，否则 1 IU 误差 → 引脚/线不连接。
- 引脚间距必须 1.27 整数倍，元件中心吸附 1.27mm 网格，ERC 才不报 off-grid。
- 运行 kicad-cli 必须隔离 conda（清 `CONDA_PREFIX` 等）+ 设 `KICAD_STOCK_DATA_HOME`。
- 用 `--mode-single` 才能让 `pcb export svg` 输出单文件（否则按目录多文件）。
- `sch export svg` 的 `-o` 在本版本当作**目录**，实际文件是 `<目录>/<sheet名>.svg`。
- 现有 kicad-cli：`/media/luskyle/DATA/project/kicad-mcp/build/kicad/kicad-cli`。
