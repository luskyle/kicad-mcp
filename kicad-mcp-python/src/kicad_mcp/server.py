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
            "- 原理图自动仿真类型选择 (kicad_sch_detect_simulation)：分析电路拓扑\n"
            "（器件 + 激励源类型）自动确定最合适的仿真类型（.tran/.op/.dc/.ac）\n"
            "并给出建议指令；kicad_sch_simulate / kicad_sch_simulate_gui 在原理图\n"
            "没有仿真指令时会自动按推荐类型注入（GUI 版会把指令文本写入原理图）。\n"
            "- 自定义元件 (kicad_sch_create_custom_symbol)：根据外部元件规格书\n"
            "（JSON 或文本表格，含引脚编号/名称/电气类型）自动生成 KiCad 符号，\n"
            "写入项目私有库（每个项目一个库，库名 <项目名>_local），挂载到\n"
            "sym-lib-table；重启 eeschema 后即可放置。\n"

            "- 原理图 KiCad GUI 仿真 (kicad_sch_simulate_gui)：打开 eeschema 内置的\n"
            "仿真器（ngspice 集成 + 波形绘图），自动运行当前电路并把波形显示在\n"
            "KiCad 的窗口中（真正的 KiCad GUI 查看仿真结果）。前提：原理图含仿真\n"
            "指令（.tran 等）与仿真元件。\n"
            "- 可视化反馈 (kicad_sch_render / kicad_pcb_render)：把原理图/PCB 渲染成\n"
            "SVG（文本，可直接读取坐标/连线验证绘制）或 PNG 3D 图（给人看）。\n"
            "**工作流: 画 → kicad_sch_render 看图 → 修正 → 再 render**。建议每次\n"
            "绘制后用 render 确认接线/位置正确，再跑 ERC。SVG 过大时不内联，\n"
            "只返回文件路径（可减小图纸或降低 max_svg_chars 门槛）。\n"
            "- 一键成图 (kicad_sch_draw_circuit)：从电路描述 JSON（symbols + nets，\n"
            "net 的 pins 顺序隐含信号方向）自动完成布局→布线→标签→ERC→渲染。\n"
            "按行业标准约束（IEC 61082-1）：信号流左→右、电源上/地在下（电源网络\n"
            "trunk 走顶部/底部轨道）、连线少交叉（barycenter）、Junction 明确连接点。\n"
            "电路 JSON 可选 no_connect_marks=true 给未用引脚打 X。适合一次画完整\n"
            "张原理图；需要微调布局时可用 kicad_sch_auto_layout + kicad_sch_auto_route。\n"
            "- 标准审查 (kicad_sch_standards_check)：按行业标准（IEC 61082-1 布局规则 /\n"
            "IPC-2612 图纸规范）对原理图跑一遍质量清单（位号值齐全、1.27mm 网格、\n"
            "无重叠、不越界、导线交叉数、电源上/地在下、网络命名、ERC），并给修复建议。\n"
            "**每次设计都要遵守**: 1) 信号流左→右、输入左输出右；2) 电源(VCC)上、地(GND)下；\n"
            "3) 导线少交叉；4) 每个符号有参考位号+值；5) 引脚在 1.27mm 网格；6) 未用引脚\n"
            "打 NoConnect(X)；7) 电源/关键网络有明确标签。draw_circuit 会自动跑标准审查。\n"
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
