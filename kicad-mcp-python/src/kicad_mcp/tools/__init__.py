"""MCP 工具包：按领域聚合所有工具。"""

from . import bus
from . import circuit
from . import common
from . import draw_report
from . import overlaps
from . import pcb
from . import project
from . import prompts
from . import quality
from . import reload
from . import render
from . import schematic
from . import standards
from . import symbol_lib
from . import symbol_browser

ALL_TOOLS = [
    *common.ALL_TOOLS,
    *draw_report.ALL_TOOLS,
    *pcb.ALL_TOOLS,
    *render.ALL_TOOLS,
    *circuit.ALL_TOOLS,
    *bus.ALL_TOOLS,
    *standards.ALL_TOOLS,
    *quality.ALL_TOOLS,
    *reload.ALL_TOOLS,
    *project.ALL_TOOLS,
    *prompts.ALL_TOOLS,
    *overlaps.ALL_TOOLS,
    *schematic.ALL_TOOLS,
    *symbol_lib.ALL_TOOLS,
    *symbol_browser.ALL_TOOLS,
]

__all__ = ["ALL_TOOLS", "common", "draw_report", "pcb", "render", "circuit", "bus", "overlaps", "project", "prompts", "quality", "reload", "standards", "schematic", "symbol_lib"]
