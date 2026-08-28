"""MCP 工具包：按领域聚合所有工具。"""

from . import bus
from . import circuit
from . import common
from . import pcb
from . import prompts
from . import quality
from . import render
from . import schematic
from . import standards
from . import symbol_lib
from . import symbol_browser

ALL_TOOLS = [
    *common.ALL_TOOLS,
    *pcb.ALL_TOOLS,
    *render.ALL_TOOLS,
    *circuit.ALL_TOOLS,
    *bus.ALL_TOOLS,
    *standards.ALL_TOOLS,
    *quality.ALL_TOOLS,
    *prompts.ALL_TOOLS,
    *schematic.ALL_TOOLS,
    *symbol_lib.ALL_TOOLS,
    *symbol_browser.ALL_TOOLS,
]

__all__ = ["ALL_TOOLS", "common", "pcb", "render", "circuit", "bus", "prompts", "quality", "standards", "schematic", "symbol_lib"]
