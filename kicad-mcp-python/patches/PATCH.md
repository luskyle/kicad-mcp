# 补丁：让 AI 能通过 API 创建/查询/修改/删除原理图元素

补丁文件：`patches/kicad-schematic-api.patch`（873 行，12 个源文件）

## 解决的问题

KiCad 源码的 API 基础设施（`common/api/`）只实现了 **PCB** 元素的创建
（`TypeNameFromAny` 只映射 board 类型）。原理图（schematic）一侧：

- `TypeNameFromAny` 不认识 `kiapi.schematic.types.*` → `CreateItems` 返回
  `ISC_INVALID_TYPE`；
- 即便类型能识别，`SchematicLayer` 枚举只有 `SL_UNKNOWN`、`SCH_TEXT`/`SCH_SYMBOL`
  也没有序列化实现；
- `eeschema` 的 `API_HANDLER_SCH` 只注册了 `GetOpenDocuments`（没有
  `SaveDocument`/`GetItems`/`GetItemsById`），画完无法保存、无法读回；
- `API_HANDLER_SCH` 构造器没把 frame 传给 `API_HANDLER_EDITOR` 基类，导致
  `checkForBusy()` 空指针崩溃；
- 多元素一次创建会段错误（`pushCurrentCommit` 在循环内销毁 commit，第二个
  item 悬空指针）；`deleteItemsInternal`/`getItemFromDocument` 是空 TODO；
- 基础 `Text` 消息无 id 字段、Label 序列化无文本 → 无法更新/删除、标签网络名丢失。

实测在 KiCad 10.0.5 上发送 `CreateItems(kiapi.schematic.types.Text)` 会触发
**eeschema 段错误崩溃**（无效 item → `Deserialize` 崩溃）。

## 补丁内容

| 文件 | 改动 |
|---|---|
| `api/proto/schematic/schematic_types.proto` | 补全 `SchematicLayer` 枚举（SL_WIRE/SL_BUS/SL_NOTES）；新增 `Symbol`/`Field` 消息；`Text` 加 `id` 字段；`Symbol` 加 `orientation_degrees` 字段 |
| `common/api/api_enums.cpp` | 实现 `SchematicLayer` ↔ `SCH_LAYER_ID` 双向映射 |
| `common/api/api_utils.cpp` | `TypeNameFromAny` 增加 7 个 schematic 类型映射（Text/Line/Local/Global/Hierarchical/Directive Label/Symbol） |
| `common/api/api_handler_editor.cpp` | **修复 `handleDeleteItems`**：把每个删除结果加入 `response.deleted_items`（原代码漏掉，响应永远为空） |
| `eeschema/sch_text.h/.cpp` | `SCH_TEXT::Serialize/Deserialize`（Text 消息，含 **id**） |
| `eeschema/sch_symbol.h/.cpp` | `SCH_SYMBOL::Serialize/Deserialize`（Symbol 消息：LIB_ID+位置+字段+**orientation_degrees 角度**） |
| `eeschema/sch_label.h/.cpp` | **补全 4 个 Label 类（Local/Global/Hierarchical/Directive）的序列化**：官方 3 个是 `UNIMPLEMENTED_FOR`、1 个只写 id+position；补全为含**标签文本**（网络名） |
| `eeschema/api/api_handler_sch.h/.cpp` | ① `createSymbolFromAny`：从项目符号库表加载 `LIB_SYMBOL`；② **修复构造器**：`API_HANDLER_EDITOR( aFrame )`；③ 无 container 时默认 `m_frame->GetScreen()->Schematic()`；④ **`SaveDocument` handler**；⑤ **`GetItems` handler**（读回 Text/Symbol/Line/Label，带 id）；⑥ **实现 `deleteItemsInternal`/`getItemFromDocument`**（删除按 KIID 走 commit）；⑦ **修复多元素创建崩溃**：`pushCurrentCommit` 移出循环、循环后统一提交 |
| `pcbnew/exporters/step/step_pcb_model.cpp` | **编译兼容**：OCC 7.7+ 的 `XCAFDoc_Editor::Extract` 在 OCC 7.5 不存在，用 `#if OCC_VERSION_HEX >= 0x070700` 分支回退到 `TDocStd_XLinkTool::Copy` |

## 补丁后支持的元素（`CreateItems` / `GetItems` / `UpdateItems` / `DeleteItems`）

- `kiapi.schematic.types.Text` → SCH_TEXT（文本注释；含 id，可更新/删除）
- `kiapi.schematic.types.Line` → SCH_LINE（连线/图形线，层 = wire/bus/notes；含 id）
- `kiapi.schematic.types.LocalLabel/GlobalLabel/HierarchicalLabel/DirectiveLabel`
  → 网络标签（**含文本**，即网络名）
- `kiapi.schematic.types.Symbol` → SCH_SYMBOL（放置元件，从库加载；含 **orientation_degrees** 0/90/180/270）

## 补丁后支持的命令（eeschema API handler）

- `GetOpenDocuments`（原有）
- `CreateItems` / `UpdateItems` / `DeleteItems`（基类分发 + 上述实现）
- `SaveDocument`（**patch 新增**，保存原理图 + 项目）
- `GetItems`（**patch 新增**，按 `KiCadObjectType` 读回元素，含 KIID）

> `GetItemsById`/`HitTest` 仍受限（`getItemFromDocument` 已实现，可支持 HitTest；
> `GetItemsById` 未注册）。

## 如何应用

```bash
cd <kicad-src>
git apply kicad-mcp-python/patches/kicad-schematic-api.patch
# 或直接使用工作区里已打好的改动（git diff 可见）
```

## 编译验证（本机已完成，2026-08-26）

本机 Ubuntu 22.04 + KiCad PPA 的 wxWidgets 3.2 完整编译成功：
所有可执行文件生成于 `build/`（`kicad/kicad`、`eeschema/eeschema`、
`pcbnew/pcbnew`、`kicad/kicad-cli` 等，版本 10.0.6-rc2）。

关键编译注意事项：
- **必须隔离 conda**：编译与运行时
  `export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`
  且 `env -u CONDA_PREFIX -u CONDA_DEFAULT_ENV ...`，否则 conda 的
  wxWidgets（缺 webview）/其他库会污染构建。
- 依赖：wxWidgets 3.2（PPA `ppa:kicad/kicad-9.0-releases`）、OCC 7.5.1（apt
  libocct-*）、nng、ngspice、protobuf、boost、glm 等（`sudo ./install-deps.sh`）。

只改 eeschema 相关时增量编译：
```bash
cd build && ninja eeschema
```

## 运行验证（编译版 eeschema）

**资源路径**：编译版默认从编译时路径（`/usr/local/share/kicad`）找
`resources/images.tar.gz` 等资源。若资源在其他位置，设置：

```bash
export KICAD_STOCK_DATA_HOME=/path/to/share/kicad   # 覆盖资源/库存数据路径
```

> ⚠️ 不要设置 `APPDIR`（指向 AppImage 会加载错误的 kiface，导致启动报错阻塞
> API）；也不要依赖 `KICAD_PATH`（它只影响 Python 脚本路径，不覆盖资源路径）。

**符号库表**：`~/.config/kicad/10.0/sym-lib-table` 需含目标库（如 Device）：

```
(sym_lib_table
	(version 7)
	(lib (name "Device") (type "KiCad") (uri "/path/to/symbols/Device.kicad_symdir") (options "") (descr "Device symbols"))
)
```

**启动 + 验证**（本机实测通过）：

```bash
cd <kicad-src>/build
DISPLAY=:0 KICAD_STOCK_DATA_HOME=/path/to/share/kicad \
  ./eeschema/eeschema demos/stickhub/StickHub.kicad_sch &

cd kicad-mcp-python
PYTHONPATH=src python -c "
from kicad_mcp.tools.schematic import kicad_sch_add_symbol, kicad_sch_add_text, kicad_sch_add_line
print(kicad_sch_add_text('Hello', 120, 80))
print(kicad_sch_add_line(100, 100, 150, 100, 'wire'))
print(kicad_sch_add_symbol('Device', 'R', 130, 90, reference='R1', value='10k'))
"
```

**实测结果（本机，2026-08-27）**：
- 创建：文本、连线、符号（含 **orientation_degrees=90 旋转**）全部 `ISC_OK(1)`；
- **一次创建多个元素不再崩溃**（修复 `pushCurrentCommit` 悬空指针）；
- `GetItems` 读回 Text/Symbol/Line/Label（含完整 KIID 与字段）；StickHub 现有
  符号角度分布（0/90/180/270）与文件一致；
- `UpdateItems` 更新文本内容+位置、`DeleteItems` 按 KIID 删除，均 `ISC_OK(1)`
  并即时可读回确认；
- **标签**（Global/Local/Hier/Directive）创建 + 读回**网络名文本**成功；
- `SaveDocument` 成功落盘（`.kicad_sch` 中可见 `(symbol "Device:R"`、
  `(text "Hello from MCP ..."`、`(wire ...)`）；
- MCP stdio 端到端 **14 个工具**全部通过：`tests/test_mcp_sch.py`（创建）+
  `tests/test_mcp_sch_crud.py`（查询/标签/更新/删除）+ `tests/verify_crud.py` +
  `tests/verify_label.py`。

## 已知限制 / 后续工作

- `GetItemsById` 未注册（`getItemFromDocument` 已实现，可顺带补上）。
- `SCH_SYMBOL` 创建的 sheet 实例（`SCH_SYMBOL_INSTANCE`）未显式设置——实际
  提交验证正常，必要时补充。
- Symbol 的**镜像**未暴露（`orientation_degrees` 只含角度，镜像标志被掩掉）。
