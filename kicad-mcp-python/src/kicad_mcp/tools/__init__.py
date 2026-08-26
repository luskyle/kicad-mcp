"""MCP 工具包：按领域聚合所有工具。"""

from . import common
from . import pcb
from . import schematic

ALL_TOOLS = [
    *common.ALL_TOOLS,
    *pcb.ALL_TOOLS,
    *schematic.ALL_TOOLS,
]

__all__ = ["ALL_TOOLS", "common", "pcb", "schematic"]
