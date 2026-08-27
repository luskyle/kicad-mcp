"""KiCad MCP Server。

通过 stdio 暴露 MCP 工具，工具内部连接本机运行中的 KiCad API Server，
让 AI 客户端可以查询/控制 KiCad 绘制原理图与 PCB。
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .tools import ALL_TOOLS


def build_server() -> MCPServer:
    mcp = MCPServer(
        "kicad-mcp",
        instructions=(
            "这个 MCP 服务器用于控制本机正在运行的 KiCad。"
            "所有工具都要求 KiCad 已启动并在偏好设置中启用了 API Server "
            "(Preferences -> Api -> Enable server)。"
            "KiCad 中 kicad(项目管理器)、eeschema(原理图)、pcbnew(PCB) 是独立进程，"
            "各有独立的 API socket，服务器会自动发现并按文档类型路由。\n"
            "当前可用能力:\n"
            "- 连通性与版本 (kicad_ping / kicad_get_version)\n"
            "- 查询打开的文档并保存 (kicad_get_open_documents / kicad_save_document)\n"
            "- PCB 绘制: 添加文本/走线、查询元素 (kicad_pcb_add_text / "
            "kicad_pcb_add_track / kicad_get_pcb_items)\n"
            "- 原理图绘制 (kicad_sch_add_text / kicad_sch_add_line / "
            "kicad_sch_add_symbol / kicad_sch_add_label)\n"
            "- 原理图引脚感知绘制 (kicad_sch_add_symbol 会返回每个引脚的绝对坐标；"
            "kicad_sch_get_symbol_pins 查询引脚；kicad_sch_connect 按引脚名连线，"
            "自动对齐引脚坐标并支持旋转后的引脚位置)\n"
            "- 原理图查询/修改/删除 (kicad_sch_get_items / kicad_sch_update_text / "
            "kicad_sch_delete_item)\n"
            "重要: 原理图工具需要「已打补丁」的 KiCad（补丁见仓库源码："
            "SchematicLayer 枚举 + TypeNameFromAny schematic 映射 + "
            "SCH_TEXT/SCH_SYMBOL/Label 序列化 + GetItems/SaveDocument handler + "
            "多元素创建修复 + 符号实例渲染修复）。未打补丁的 KiCad 10.0.5 使用这些"
            "工具会导致 eeschema 崩溃，请勿在 10.0.5 上调用。"
            "坐标系注意: 原理图坐标 1mm = 1e4 内部单位（不是 PCB 的 1e6）。"
        ),
    )
    for fn in ALL_TOOLS:
        mcp.add_tool(fn)
    return mcp


def main() -> None:
    server = build_server()
    server.run()  # 默认 stdio 传输


if __name__ == "__main__":
    main()
