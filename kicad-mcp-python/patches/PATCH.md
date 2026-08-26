# 补丁：让 AI 能通过 API 创建原理图元素

补丁文件：`patches/kicad-schematic-api.patch`（366 行，9 个源文件）

## 解决的问题

KiCad 源码的 API 基础设施（`common/api/`）只实现了 **PCB** 元素的创建
（`TypeNameFromAny` 只映射 board 类型）。原理图（schematic）一侧：

- `TypeNameFromAny` 不认识 `kiapi.schematic.types.*` → `CreateItems` 返回
  `ISC_INVALID_TYPE`；
- 即便类型能识别，`SchematicLayer` 枚举只有 `SL_UNKNOWN`、`SCH_TEXT`/`SCH_SYMBOL`
  也没有序列化实现。

实测在 KiCad 10.0.5 上发送 `CreateItems(kiapi.schematic.types.Text)` 会触发
**eeschema 段错误崩溃**（无效 item → `Deserialize` 崩溃）。

## 补丁内容

| 文件 | 改动 |
|---|---|
| `api/proto/schematic/schematic_types.proto` | 补全 `SchematicLayer` 枚举（SL_WIRE/SL_BUS/SL_NOTES）；新增 `Symbol`/`Field` 消息 |
| `common/api/api_enums.cpp` | 实现 `SchematicLayer` ↔ `SCH_LAYER_ID` 双向映射 |
| `common/api/api_utils.cpp` | `TypeNameFromAny` 增加 7 个 schematic 类型映射（Text/Line/Local/Global/Hierarchical/Directive Label/Symbol） |
| `eeschema/sch_text.h/.cpp` | 新增 `SCH_TEXT::Serialize/Deserialize`（Text 消息） |
| `eeschema/sch_symbol.h/.cpp` | 新增 `SCH_SYMBOL::Serialize/Deserialize`（Symbol 消息：LIB_ID+位置+字段） |
| `eeschema/api/api_handler_sch.h/.cpp` | 新增 `createSymbolFromAny`：从项目符号库表加载 `LIB_SYMBOL` 后构造 `SCH_SYMBOL` |

## 补丁后支持的元素（`CreateItems`）

- `kiapi.schematic.types.Text` → SCH_TEXT（文本注释）
- `kiapi.schematic.types.Line` → SCH_LINE（连线/图形线，层 = wire/bus/notes）
- `kiapi.schematic.types.LocalLabel/GlobalLabel/HierarchicalLabel/DirectiveLabel`
  → 标签（位置已支持；文本字段序列化仍待补全）
- `kiapi.schematic.types.Symbol` → SCH_SYMBOL（放置元件，从库加载）

## 如何应用

```bash
cd <kicad-src>
git apply kicad-mcp-python/patches/kicad-schematic-api.patch
# 或直接使用工作区里已打好的改动（git diff 可见）
```

## 如何编译验证

KiCad 完整构建需要大量依赖（wxWidgets、boost、glm、OCC、ngspice、nng、protobuf
等）。本机（2026-08-26 检查）缺少 wxWidgets/glm/OCC/nng/protobuf，无法直接编译。

建议的验证路径：

```bash
# 1) 安装构建依赖（Ubuntu/Debian）
sudo ./install-deps.sh

# 2) 配置并编译（可只编 eeschema 及其依赖）
cmake -S . -B build -G Ninja -DKICAD_SCRIPTING=OFF
cmake --build build --target eeschema -j$(nproc)

# 3) 用编译出的 eeschema 替换 AppImage 内二进制（需解包-替换-重打包）
#    或直接把源码目录作为 KICAD_PATH 运行
```

## 补丁后如何用 Python 客户端验证

启动打补丁的 eeschema 并打开原理图后：

```bash
cd kicad-mcp-python
PYTHONPATH=src python -c "
import kicad_mcp.client
from kicad_mcp.tools.schematic import kicad_sch_add_symbol, kicad_sch_add_text, kicad_sch_add_line
print(kicad_sch_add_text('Hello', 120, 80))
print(kicad_sch_add_line(100, 100, 150, 100, 'wire'))
print(kicad_sch_add_symbol('Device', 'R', 130, 90, reference='R1', value='10k'))
"
```

预期：创建成功，`CreateItemsResponse` 中 `ItemStatusCode == ISC_OK(1)`，原理图编辑器
中可见新增元素。

## 已知限制 / 后续工作

- 标签（Label）的**文本**字段序列化仍缺失（只有位置）——如需支持需补全
  `SCH_LABEL` 系列在 `Serialize/Deserialize` 中对 `text` 的处理。
- 符号暂不支持**旋转/镜像**（Symbol 消息未含 orientation 字段）。
- `SCH_SYMBOL` 创建的 sheet 实例（`SCH_SYMBOL_INSTANCE`）未设置——需要在实际
  原理图提交时确认，必要时补充。
