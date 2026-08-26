# kicad-mcp-python

通过 **MCP（Model Context Protocol）** 让 AI 控制 KiCad 绘制原理图与 PCB。

本模块是一个独立的 Python MCP Server：AI 客户端（Claude Desktop / VS Code Copilot 等）
通过 stdio 连接它，它在内部通过 KiCad 内置的 **API Server**（nng + protobuf）与正在运行的
KiCad 通信，从而读取、创建、修改原理图和 PCB 文档。

```
AI 客户端 ──MCP/stdio──▶ kicad-mcp (Python) ──nng+protobuf──▶ KiCad API Server
                                                              ├─ kicad  (项目管理器, api.sock)
                                                              ├─ eeschema (原理图, api-<pid>.sock)
                                                              └─ pcbnew  (PCB, api-<pid>.sock)
```

> KiCad 8+ 中 `kicad` / `eeschema` / `pcbnew` 是**独立进程**，各有自己的 API socket。
> 本模块会自动发现所有 socket，并按文档类型路由到正确的进程。

## 环境要求

- KiCad **10.x**（8.0+ 才有 API Server）
- KiCad 已启动，且偏好设置已启用 API Server（`Preferences → Api → Enable server`）
- Python 3.10+

## 安装

```bash
# 1. 安装 Python 依赖（使用 base conda 环境即可）
conda run -n base pip install mcp pynng grpcio-tools protobuf

# 2. 从 KiCad 源码仓库的 api/proto 生成 protobuf 绑定
PYTHON=/path/to/python ./gen_proto.sh
```

生成产物位于 `src/kicad_mcp/proto/`（已包含 `__init__.py` 的包结构）。

## 使用

### 启动 MCP Server（stdio）

```bash
PYTHONPATH=src python -m kicad_mcp
```

### 配置 AI 客户端

以 Claude Desktop / 支持 MCP 的客户端为例，注册一个 stdio server：

```json
{
  "mcpServers": {
    "kicad": {
      "command": "/home/luskyle/anaconda3/bin/python",
      "args": ["-m", "kicad_mcp"],
      "env": { "PYTHONPATH": "/media/luskyle/DATA/project/kicad-mcp/kicad-mcp-python/src" }
    }
  }
}
```

### 连通性自检

```bash
PYTHONPATH=src python -m kicad_mcp.check
```

## 提供的工具

| 工具 | 说明 |
|---|---|
| `kicad_ping` | 检查与 KiCad 的连接 |
| `kicad_get_version` | 返回 KiCad 版本 |
| `kicad_get_open_documents` | 列出打开的文档（schematic/pcb/...） |
| `kicad_save_document` | 保存打开的文档 |
| `kicad_pcb_add_text` | 在 PCB 上创建文本（BoardText） |
| `kicad_pcb_add_track` | 在 PCB 上创建走线（Track） |
| `kicad_get_pcb_items` | 查询 PCB 元素统计 |

## 验证情况（KiCad 10.0.5, 2026-08-26）

| 能力 | 状态 |
|---|---|
| 连接 / 版本 / 查询打开文档 | ✅ 通过 |
| PCB 创建元素（BoardText/Track，`CreateItems`） | ✅ 通过（已验证落盘） |
| PCB 查询元素 | ✅ 通过 |
| 原理图创建元素（`CreateItems`） | ✅ 附源码补丁（`patches/`）；补丁前 10.0.5 会段错误，补丁后需重新编译 eeschema |

### 为什么原理图创建在 10.0.5 会崩溃

KiCad 源码 `common/api/api_utils.cpp` 的 `TypeNameFromAny()` 原只映射了 **board** 类型
（Track/Arc/Via/BoardText/...），**没有实现 schematic 类型**。10.0.5 收到
`type.googleapis.com/kiapi.schematic.types.Text` 的 `CreateItems` 请求时，会创建一个
无效 item，在 `Deserialize` 阶段段错误崩溃。

### 已提供的源码补丁

本仓库已附带补丁 `patches/kicad-schematic-api.patch`（说明见 `patches/PATCH.md`）：
- `TypeNameFromAny` 增加 schematic 类型映射
- 补全 `SchematicLayer` 枚举 + `api_enums` 映射
- 新增 `SCH_TEXT` / `SCH_SYMBOL` 序列化（符号从库加载在 API handler 层）
- 新增 `Symbol`/`Field` proto 消息

**编译该补丁后的 KiCad** 后，原理图工具（`kicad_sch_add_text` /
`kicad_sch_add_line` / `kicad_sch_add_symbol`）即可用；未打补丁的 10.0.5
**不要调用这些工具**（会崩溃 eeschema）。

## 项目结构

```
kicad-mcp-python/
├── gen_proto.sh                # 从 api/proto 生成 protobuf 绑定
├── pyproject.toml
├── src/kicad_mcp/
│   ├── client.py               # nng + protobuf 客户端（含 socket 自动发现）
│   ├── server.py               # MCP Server（stdio）
│   ├── check.py                # 连通性自检
│   ├── proto/                  # 生成的 protobuf 绑定（gen_proto.sh 产物）
│   └── tools/
│       ├── common.py           # ping/version/文档查询/保存
│       └── pcb.py              # PCB 绘制与查询工具
└── tests/
    ├── test_draw.py            # 原理图绘制验证（10.0.5 会崩溃，仅参考）
    ├── test_draw_pcb.py        # PCB 绘制验证
    └── test_mcp_stdio.py       # MCP stdio 端到端验证
```

## 常见问题

- **连接被拒绝**：KiCad 未启动，或未启用 API Server，或 `KICAD_API_SOCKET` 指向错误。
- **`no handler available`**：请求发到了错误的进程 socket（应连 `api-<pid>.sock`）。
  本模块已自动按文档类型路由；若你手动指定 socket 请注意这一点。
- **eeschema 崩溃**：不要发送 schematic 类型的 `CreateItems` 请求（见上文）。
