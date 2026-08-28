# 模板：验证 / 仿真电路

> 画完图后的验证闭环：ERC 门禁 → 标准审查 → SPICE 仿真 → Golden 回归。

## 1. ERC 门禁（交付即通过）
`draw_circuit` 画完自动跑；也可手动：
- `kicad_sch_erc_gate(sch_file=...)` → PASS/FAIL + 违规分组
  - **blocking**（必须 0）：Pin/Wire/Label not connected、off-grid、短路、电源未驱动
  - **豁免**（不阻塞）：跨页输入未驱动、Label 只连一引脚、封装库缺失
  - 电源网络（power_in 无 power_out）**自动补 PWR_FLAG** 后重跑

## 2. 标准审查（IEC 61082-1 / IPC-2612）
- `kicad_sch_standards_check(sch_file=...)`：位号值、1.27mm 网格、重叠、越界、
  导线交叉、电源上地在下、网络标签、ERC 合并。
- draw_circuit 每次画完自动跑（standards_check 默认 true）。

## 3. SPICE 仿真（行为验证）
- `kicad_sch_simulate(sch_file=...)`：自动导出 netlist → libngspice 仿真 → 波形统计。
  - 无仿真指令时 `auto_directive` 自动按电路推荐（.op/.tran/.ac/.dc）。
  - **GND 网络用标签 "0"**（SPICE 地）才能仿真，power 符号占位行会报 bad syntax。
  - RC 充电：`.ic v(OUT)=0` + `.tran ... UIC`；τ 用 63.2% 法，未饱和自动延长 .tran。
- `kicad_sch_detect_simulation(sch_file=...)`：先看推荐的仿真类型。
- `kicad_sch_simulate_gui(...)`：在 KiCad 内置仿真器画波形（需要 eeschema 打开）。

## 4. Golden 回归（防回归）
- `python tests/run_golden.py`（需 eeschema 打开空 .kicad_sch）：重画 5 个已验证电路
  （rc/divider/flash/power/matrix）→ 对比 netlist 连通性 + 标签 vs `tests/golden/`。
- 工具改动后必跑：保证电气结构没被改坏。
- 重新生成基线：`python tests/run_golden.py --gen`（仅当确认新基线正确时）。

## 常见修复
| 现象 | 处理 |
|---|---|
| "Pin not connected" | 引脚没连到线/标签；检查 stub 是否落在引脚上、Junction 是否在 |
| "off connection grid" | 端点吸附 1.27mm 网格 |
| 电源未驱动 | 门禁自动补 PWR_FLAG |
| 导线短路（共线合并） | 多引脚同列用 collector；不同网络 lane 隔离 |
| 标签压符号/导线 | 交给工具（label 默认放外侧 stub / trunk 左端 tab，1.27mm） |
