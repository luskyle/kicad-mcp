# KiCad + kicad-mcp

> **这是一个带 kicad-mcp 的 KiCad 源码仓库**：在标准 KiCad 之上，增加了
> **MCP（Model Context Protocol）能力** —— 让 AI 助手通过自然语言直接控制
> KiCad 绘制/检查/仿真原理图与 PCB，实现"你说电路，AI 画图"。

```
AI 客户端 (Claude / VS Code Copilot / …)
   │  MCP / stdio
   ▼
kicad-mcp-python  (Python MCP Server, 48 个工具)
   │  nng + protobuf（KiCad 内置 API Server）
   ▼
KiCad  (打补丁后编译)
   ├─ kicad   项目管理器   →  api.sock
   ├─ eeschema 原理图       →  api-<pid>.sock
   └─ pcbnew   PCB          →  api-<pid>.sock
```

## 这是什么

- **AI 控制 KiCad**：任何支持 MCP 的 AI 客户端，注册本仓库的 MCP Server 后，
  即可让 AI 在 KiCad 里画原理图、连线、放标签、跑 ERC、仿真、检查重叠并自动修复。
- **智能原理图引擎**：`kicad_sch_draw_circuit` 一键成图 —— 从"元件 + 网络"
  的描述自动完成 **布局 → 布线 → 标签 → ERC 门禁 → 渲染反馈**，按行业标准
  （IEC 61082-1 / IPC-2612）交付"即画即通过"的图纸。
- **打补丁的 KiCad**：官方 KiCad 的 API 只实现了 PCB 侧，原理图侧需要本仓库
  `kicad-mcp-python/patches/` 提供的补丁（补全 schematic 序列化 / GetItems /
  SaveDocument / 多元素创建 / 符号实例渲染等），详见
  [补丁说明](kicad-mcp-python/patches/PATCH.md)。

## 核心能力（48 个 MCP 工具）

| 能力域                | 代表工具                                                  | 说明                                                                                                                               |
| --------------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **一键成图**    | `kicad_sch_draw_circuit`                                | 从电路描述 JSON（symbols+nets）自动布局→布线→标签→ERC→渲染；支持`kicad_sch_auto_layout` / `kicad_sch_auto_route` 分步调用  |
| **智能布局**    | 内置                                                      | 信号流左→右分列（BFS）、barycenter 减交叉、电源上/地在下轨道、**2 引脚元件自动水平朝向**（串联直连）、间距自适应            |
| **智能布线**    | 内置                                                      | 两引脚网络**智能直连**（免 U 形绕线）、多引脚网络专业 trunk bus（每网络独占水平道 + 垂直 stub + Junction）、跨网络避让防短路 |
| **标签体系**    | `kicad_sch_add_label` / `kicad_sch_recommend_label`   | 全局/本地/层次/指令标签；输入/输出/双向/三态箭头形状；连接点方向；指令标签 点/圆/菱形/矩形                                         |
| **变换**        | `kicad_sch_transform_item`                              | 符号顺时针/逆时针旋转、水平/垂直镜像；标签连接点旋转/镜像                                                                          |
| **ERC 门禁**    | `kicad_sch_erc_gate`                                    | 结构化解析 ERC → 分类 blocking/benign；**自动补 PWR_FLAG** 修复电源未驱动，交付即通过                                       |
| **标准审查**    | `kicad_sch_standards_check`                             | 按 IEC 61082-1 / IPC-2612 审查位号值、网格、重叠、越界、交叉、电源上下、命名                                                       |
| **重叠修复**    | `kicad_sch_check_overlaps` / `kicad_sch_fix_overlaps` | 真实几何检测符号/标签/导线重叠与越界，自动重摆 + 延伸 stub 保持连通                                                                |
| **Golden 回归** | `tests/run_golden.py`                                   | 以 netlist 连通性 + 标签为判据的回归测试，防工具改动破坏既有电路                                                                   |
| **仿真**        | `kicad_sch_simulate` / `kicad_sch_simulate_gui`       | 导出 netlist 用本地 ngspice 仿真（返回节点波形）；GUI 版在 KiCad 里直接显示波形                                                    |
| **自定义元件**  | `kicad_sch_create_custom_symbol`                        | 按规格书 JSON/文本自动生成库符号，写入项目私有库                                                                                   |
| **总线**        | `kicad_sch_add_bus` 系列                                | 总线导线/标签/entry/一键连接总线                                                                                                   |
| **渲染反馈**    | `kicad_sch_render` / `kicad_pcb_render`               | 原理图导出 SVG（AI 可读坐标验证），PCB 渲染 PNG/3D                                                                                 |
| **提示词模板**  | `kicad_get_prompt_template`                             | 内置 draw-circuit / power / mcu / matrix 等模板，指导 AI 高质量画图                                                                |

## 快速开始

```bash
# 1. 编译打补丁后的 KiCad（原理图 API 需要）
cmake --preset ...   # 或用已有的 build 目录
ninja -C build eeschema kicad

# 2. 启动 KiCad 并启用 API Server（Preferences → Api → Enable server）
./build/kicad/kicad  &          # 项目管理器
./build/eeschema/eeschema xxx.kicad_sch &   # 原理图

# 3. 启动 MCP Server（stdio）
cd kicad-mcp-python
PYTHONPATH=src python -m kicad_mcp

# 4. 在 AI 客户端注册 MCP Server
#    {"mcpServers": {"kicad": {"command": "python",
#      "args": ["-m", "kicad_mcp"],
#      "env": {"PYTHONPATH": ".../kicad-mcp-python/src"}}}}
```

连通性自检：`cd kicad-mcp-python && PYTHONPATH=src python -m kicad_mcp.check`

## 智能原理图怎么用

给 AI 一段描述，例如：

> "画一个 3.3V LDO 电源：USB-C 输入，AMS1117-3.3 输出，输入输出各一个 10µF 电容，
> 输出网络叫 3V3，GND 用 0。"

AI 会调用 `kicad_sch_draw_circuit` 完成：放置元件 → 按信号流布局 → 智能布线 →
放网络标签 → 跑 ERC 门禁（自动补 PWR_FLAG）→ 标准审查 → 渲染 SVG 反馈。
如果某处标签重叠或元件挡线，AI 会再用 `kicad_sch_check_overlaps` +
`kicad_sch_fix_overlaps` 自动修复，或用 `kicad_sch_transform_item` 旋转/镜像调整。

> 详细文档：`kicad-mcp-python/README.md`（安装/配置/工具）、
> `kicad-mcp-python/docs/`（做图能力提升方案、标签与变换方案、原理图标准）、
> `kicad-mcp-python/prompts/`（AI 提示词模板）、`kicad-mcp-python/patches/PATCH.md`（补丁说明）。

## 目录结构

```
kicad-mcp-python/            # MCP Server（Python）
├── src/kicad_mcp/
│   ├── server.py            # MCP Server（stdio，注册全部工具）
│   ├── client.py            # nng + protobuf 客户端（socket 自动发现）
│   └── tools/               # 48 个 MCP 工具（common/pcb/render/circuit/bus/
│                            #   standards/quality/prompts/overlaps/schematic/
│                            #   symbol_lib/symbol_browser）
├── patches/                 # KiCad 源码补丁（原理图 API / 仿真 GUI）
├── prompts/                 # AI 提示词模板
├── tests/                   # 单元测试 + golden 回归
└── gen_proto.sh             # 从 api/proto 生成 protobuf 绑定
api/                         # KiCad API 定义（proto）
eeschema/ pcbnew/ common/ …  # KiCad 源码（含 kicad-mcp 补丁）
```

---

# KiCad README

For specific documentation about [building KiCad](https://dev-docs.kicad.org/en/build/), policies
and guidelines, and source code documentation see the
[Developer Documentation](https://dev-docs.kicad.org) website.

You may also take a look into the [Wiki](https://gitlab.com/kicad/code/kicad/-/wikis/home),
the [contribution guide](https://dev-docs.kicad.org/en/contribute/).

For general information about KiCad and information about contributing to the documentation and
libraries, see our [Website](https://kicad.org/) and our [Forum](https://forum.kicad.info/).

## Build state

KiCad uses a host of CI resources.

GitLab CI pipeline status can be viewed for Linux and Windows builds of the latest commits.

## Release status

[![latest released version(s)](https://repology.org/badge/latest-versions/kicad.svg)](https://repology.org/project/kicad/versions)
[![Release status](https://repology.org/badge/tiny-repos/kicad.svg)](https://repology.org/metapackage/kicad/versions)

## Files

* [AUTHORS.txt](AUTHORS.txt) - The authors, contributors, document writers and translators list
* [CMakeLists.txt](CMakeLists.txt) - Main CMAKE build tool script
* [copyright.h](copyright.h) - A very short copy of the GNU General Public License to be included in new source files
* [Doxyfile](Doxyfile) - Doxygen config file for KiCad
* [INSTALL.txt](INSTALL.txt) - The release (binary) installation instructions
* [uncrustify.cfg](uncrustify.cfg) - Uncrustify config file for uncrustify sources formatting tool
* [_clang-format](_clang-format) - clang config file for clang-format sources formatting tool

## Subdirectories

* [3d-viewer](3d-viewer)         - Sourcecode of the 3D viewer
* [bitmap2component](bitmap2component)  - Sourcecode of the bitmap to PCB artwork converter
* [cmake](cmake)      - Modules for the CMAKE build tool
* [common](common)            - Sourcecode of the common library
* [cvpcb](cvpcb)             - Sourcecode of the CvPCB tool
* [demos](demos)             - Some demo examples
* [doxygen](doxygen)     - Configuration for generating pretty doxygen manual of the codebase
* [eeschema](eeschema)          - Sourcecode of the schematic editor
* [gerbview](gerbview)          - Sourcecode of the gerber viewer
* [include](include)           - Interfaces to the common library
* [kicad](kicad)             - Sourcecode of the project manager
* [libs](libs)           - Sourcecode of KiCad utilities (geometry and others)
* [pagelayout_editor](pagelayout_editor) - Sourcecode of the pagelayout editor
* [patches](patches)           - Collection of patches for external dependencies
* [pcbnew](pcbnew)           - Sourcecode of the printed circuit board editor
* [plugins](plugins)           - Sourcecode for the 3D viewer plugins
* [qa](qa)                - Unit testing framework for KiCad
* [resources](resources)         - Packaging resources such as bitmaps and operating system specific files
  - [bitmaps_png](resources/bitmaps_png)       - Menu and program icons
  - [project_template](resources/project_template)          - Project template
* [scripting](scripting)         - Python integration for KiCad
* [thirdparty](thirdparty)           - Sourcecode of external libraries used in KiCad but not written by the KiCad team
* [tools](tools)             - Helpers for developing, testing and building
* [translation](translation) - Translation data files (managed through [Weblate](https://hosted.weblate.org/projects/kicad/master-source/) for most languages)
* [utils](utils)             - Small utils for KiCad, e.g. IDF, STEP, and OGL tools and converters
