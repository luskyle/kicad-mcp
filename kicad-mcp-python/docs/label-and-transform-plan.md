# 标签类型 / 形状 / 方向 + 元素旋转镜像 —— 方案

> 用户反馈：目前只用全局标签，但 KiCad 有完整的标签体系（类型/形状/方向）和
> 元素变换（旋转/镜像）。AI 要能**判断用哪种标签**，并**灵活运用旋转/镜像**绘制。

## 1. KiCad 标签体系（AI 要能选对）

| 标签类型 | 用途 | shape（形状） | spin（连接点方向） |
|---|---|---|---|
| **全局标签 GlobalLabel** | 跨页信号（多页工程连接） | 输入/输出/双向/三态/无源（箭头形状） | 左/右/上/下 |
| **本地标签 LocalLabel**（net label） | 单页内命名网络（同一页引用） | 无 | 左/右/上/下 |
| **层次标签 HierLabel** | 层次图（子图端口） | 输入/输出/双向/三态/无源 | 左/右/上/下 |
| **指令标签 DirectiveLabel**（flag） | ERC 指令/网络类（如差分对、类、仿真） | **点/圆/菱形/矩形** | 左/右/上/下 |

**选择规则（推荐工具 `kicad_sch_recommend_label`）**：
- **跨页信号** → `global`；**单页内信号** → `local`；**层次图端口** → `hier`；
  **ERC/仿真指令**（差分对、no-connect 替代、netclass）→ `directive`（flag）。
- **shape 按信号方向**：输入引脚接收信号 → `input`；输出/驱动 → `output`；
  双向（数据线 DM/DP、I2C SDA/SCL、USB）→ `bidirectional`；三态 → `tri_state`；
  纯无源网络名 → `unspecified`（无箭头）。
- **spin 按引脚所在侧**：右侧引脚 → `left`（文字在连接点左侧，信号从右进）；
  左侧引脚 → `right`；顶部引脚 → `down`；底部引脚 → `up`。
- **电源网络**：用 `power:PWR_FLAG`（power_out）或本地标签，不用 global 箭头。

## 2. 元素变换（旋转 / 镜像）

| 变换 | 符号（Symbol） | 标签（Label） | 线段/图形 |
|---|---|---|---|
| 顺时针旋转 | orientation_degrees -90（或 +90） | spin 右旋一次 | 坐标绕中心旋转 |
| 逆时针旋转 | orientation_degrees +90 | spin 左旋一次 | 坐标绕中心旋转 |
| 水平镜像（X 翻转） | SYM_MIRROR_X | spin 左右互换 | x 坐标取反 |
| 垂直镜像（Y 翻转） | SYM_MIRROR_Y | spin 上下互换 | y 坐标取反 |

**工具 `kicad_sch_transform_item(item_id, rotate, mirror)`**：对已放置元素做变换，
供 AI 调整元件方向/引脚朝向，让连线更顺（减少交叉、对齐信号流向）。

## 3. 需要扩展（C++ patch + proto + 工具）

### 3.1 proto 字段（schematic_types.proto）
- `LabelShape` 枚举（unspecified/input/output/bidirectional/tri_state）
- `LabelSpin` 枚举（left/right/up/down，= SPIN_STYLE LEFT=0/UP=1/RIGHT=2/BOTTOM=3）
- `DirectiveShape` 枚举（point/circle/diamond/rectangle，= FLAG_DOT/CIRCLE/DIAMOND/RECTANGLE）
- `SymbolMirror` 枚举（none/x/y）
- GlobalLabel/LocalLabel/HierLabel/DirectiveLabel 加 `shape`/`spin`（Directive 加 `directive_shape`）
- Symbol 加 `mirror`

### 3.2 C++（sch_label.cpp / sch_symbol.cpp）
- 4 个 label 的 Serialize/Deserialize：读写 shape/spin（directive 加 directive_shape）
- Symbol Serialize/Deserialize：读写 mirror（SYM_MIRROR_X/Y）

### 3.3 Python 工具
- `kicad_sch_add_label` 加 `shape` / `spin` / `directive_shape`
- 新增 `kicad_sch_transform_item(item_id, rotate="cw"|"ccw", mirror="h"|"v")`
- 新增 `kicad_sch_recommend_label(net_name, pin_type, cross_page)`：返回推荐的
  标签类型 + shape + spin（AI 可先问它再放置）

### 3.4 draw_circuit 集成
- net 描述加 `label_kind`（local/global/hier/directive）、`label_shape`、`label_spin`
- 默认：跨页→global、单页→local；shape 按引脚电气类型自动推断

## 4. 落地顺序（全部 ✅ 2026-08-28 完成）
1. C++ patch（proto + 序列化）→ gen_proto → ninja 编译 ✅
   - sch_label.cpp: 4 标签 Serialize/Deserialize 读写 shape/spin/directive_shape
   - sch_symbol.cpp: Serialize 输出 mirror / Deserialize 应用 mirror（增量 SetOrientation）
2. Python 工具（add_label 增强 / transform_item / recommend_label）✅
   - kicad_sch_add_label 加 shape/spin/directive_shape
   - kicad_sch_transform_item(item_id, rotate=cw/ccw, mirror=x/y)
   - kicad_sch_recommend_label(net_name, pin_type, cross_page, hierarchical, purpose)
3. draw_circuit 集成 label_kind/shape/spin ✅（nets[].label_shape/label_spin/directive_shape + 顶层默认）
4. prompt 模板更新（标签选择规则）✅（draw-circuit.md 加"标签选型规则"+"旋转/镜像"节）
5. golden/回归验证 ✅（5/5 通过；标签 shape/spin round-trip、符号旋转/镜像引脚翻转、SVG/文件确认）
