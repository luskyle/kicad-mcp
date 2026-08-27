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
            "自动使用 KiCad 计算的引脚位置并支持旋转后的引脚)\n"
            "- 原理图查询/修改/删除 (kicad_sch_get_items / kicad_sch_update_text / "
            "kicad_sch_delete_item)\n"
            "- 原理图 ERC 电气规则检查 (kicad_sch_erc)：用 KiCad 官方 ERC 验证"
            "绘制结果，无违规才算真无误。建议先保存再运行 ERC。\n"
            "- 原理图 SPICE 电路仿真 (kicad_sch_simulate)：导出 netlist 后用本机"
            "libngspice 执行仿真，返回各节点电压/电流波形与统计，用于验证电路"
            "行为是否符合预期（如 RC 充电、分压、放大等）。观测向量默认自动提取"
            "所有非地节点，也可手动指定 vectors=；可用 extra= 注入 ngspice 指令"
            "（如 '.ic v(/OUT)=0' 让电容从 0V 充电）。\n"

            "- 原理图 KiCad GUI 仿真 (kicad_sch_simulate_gui)：打开 eeschema 内置的\n"
            "仿真器（ngspice 集成 + 波形绘图），自动运行当前电路并把波形显示在\n"
            "KiCad 的窗口中（真正的 KiCad GUI 查看仿真结果）。前提：原理图含仿真\n"
            "指令（.tran 等）与仿真元件。\n"
            "ERC 注意事项: 元件中心放在 1.27mm 网格（add_symbol 默认吸附）；"
            "竖直放置的元件若上下引脚连线共线，KiCad 会合并 wire 导致引脚被埋、"
            "ERC 报未连接——可旋转元件（如电池横放）让引脚在左右，连线不共线。\n"
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
