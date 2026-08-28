# 原理图设计行业标准与 kicad-mcp 约束映射

> 目的：让 `kicad_sch_draw_circuit` / `kicad_sch_auto_layout` 等成图工具画出的
> 原理图符合行业标准（可读性 + 规范性），而不只是"能连上、ERC 通过"。
> 本文档把行业标准提炼成**可执行的规则**，并标注在代码中的落点。

## 一、相关行业标准（公认）

| 标准 | 名称 / 内容 | 关注点 |
|---|---|---|
| **IEC 61082-1** | Preparation of documents used in electrotechnology — Part 1: Rules | **原理图文档规则**：结构、布局、信号流向、连线规则 |
| **IEEE Std 315**（原 ANSI Y32.2） | Graphic Symbols for Electrical and Electronics Diagrams | 电气图形符号规范（美国体系） |
| **IEC 60617** | Graphical symbols for diagrams | 图形符号（国际/中国 GB 体系） |
| **IPC-2612**（IPC-2610 系列） | Sectional Requirements for Electronic Diagram Data Description | 原理图数据描述/图纸规范（含参考位号、值标注） |
| **IEC 81346**（原 IEC 61346） | Reference designations for technical systems | 参考位号（R/C/U 等）体系 |
| **IEEE 315A** | 315 的补充 | 符号补充 |

> 说明：符号**外形**遵循 IEEE 315 / IEC 60617（由 KiCad 符号库保证）；本文档
> 主要把 **IEC 61082-1**（文档布局规则）落实成代码约束。IPC-2612 强调图纸数据
> 完整（位号/值/引脚标注齐全）。

## 二、IEC 61082-1 核心规则 → 代码落点

| # | 规则 | 含义 | kicad-mcp 落点 |
|---|---|---|---|
| 1 | **信号流从左到右，输入在左、输出在右** | 阅读顺序 | `_flow_stages`：按 netlist 引脚顺序做 BFS 分级（stage=列），源在左 |
| 2 | **电源（正）在上、地（负）在下** | 电源轨道惯例 | `_power_rail_lanes`：GND 网络 trunk 放底部轨道、VCC 类放顶部轨道 |
| 3 | **连线尽量少交叉** | 可读性 | `_barycenter_order`：列内按邻居平均行序排序（Sugiyama barycenter 法） |
| 4 | **同一网络优先走一条"干道"（trunk）** | 结构清晰 | `_route_net_trunk`：每网络独立水平 trunk + 引脚垂直 stub |
| 5 | **导线连接点用 Junction 明确标注** | 避免歧义 | `_create_lines`：在每个 stub-trunk 汇合点放 Junction |
| 6 | **网格化布局（一致间距）** | 对齐 | `_snap_grid` 1.27mm 网格；列/行间距自适应符号尺寸 |
| 7 | **每个符号标注参考位号 + 值** | 数据完整（IPC-2612） | `_place_symbols` 设置 Reference/Value 字段 |
| 8 | **未用引脚打 X（NoConnect）** | 明确"有意不连" | `_mark_unused_pins`（选项 `no_connect_marks`） |
| 9 | **电源网络用标签/符号明确命名** | 网络可辨识 | 电源网络本地标签（GND→"0"，VCC/3V3 用原名） |
| 10 | **图纸留有边距、不越界** | 图纸规范 | `PAGE_MARGIN_MM` 检查（`kicad_sch_check_layout`） |

## 三、行业"惯例"补充（非强制但被广泛遵循）

- **退耦电容靠近 IC 电源引脚**：本工具暂不自动做（属 L2.5 增强候选），用户可显式放。
- **总线（bus）用于并行信号**：需要 L3 的 Bus 支持（C++ patch）后实现。
- **同页内网络名不重复、不同网络不共用同名标签**：由用户输入保证，ERC 会检查。
- **图形符号方向**：无源件在信号路径上横放（`orient:90`，引脚左右）、电源符号竖直，
  更符合阅读习惯（可由用户传 `orient` 控制）。

## 四、设计原则（落到代码里的优先级）

1. **先保证电气正确**（ERC 通过 + 网表正确）——这是底线。
2. **再保证可读**（信号流向、少交叉、电源轨道、Junction）。
3. **最后保证规范**（位号/值/未用引脚 X/边距）。

任何"美观"优化都不得牺牲第 1 条（ERC/网表），否则自动回退。
