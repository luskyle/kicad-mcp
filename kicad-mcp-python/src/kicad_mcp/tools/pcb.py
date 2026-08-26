"""KiCad MCP PCB 工具：查询与绘制 PCB 元素。

注意：原理图(SCH)的创建类 API 在 KiCad 10.0.5 上会触发 eeschema 段错误
（`TypeNameFromAny` 尚未实现 schematic 类型），因此这里只暴露 PCB 创建工具。
"""

from __future__ import annotations

from typing import Optional

from ..client import (
    DOCTYPE_PCB,
    KiCadClient,
    find_document_socket,
)
from ..proto.board import board_types_pb2
from ..proto.common.types import base_types_pb2
from ..proto.common.types import enums_pb2

MM = 1_000_000  # 1mm = 1e6 nm


# 常用板层名 -> BoardLayer 枚举值
LAYERS = {
    "f.cu": board_types_pb2.BL_F_Cu,
    "b.cu": board_types_pb2.BL_B_Cu,
    "f.silkscreen": board_types_pb2.BL_F_SilkS,
    "b.silkscreen": board_types_pb2.BL_B_SilkS,
    "f.mask": board_types_pb2.BL_F_Mask,
    "b.mask": board_types_pb2.BL_B_Mask,
    "f.paste": board_types_pb2.BL_F_Paste,
    "b.paste": board_types_pb2.BL_B_Paste,
    "dwgs.user": board_types_pb2.BL_Dwgs_User,
    "cmts.user": board_types_pb2.BL_Cmts_User,
    "eco1.user": board_types_pb2.BL_Eco1_User,
    "eco2.user": board_types_pb2.BL_Eco2_User,
}

# 可查询的 PCB 对象类型名 -> KOT 枚举值
ITEM_TYPES = {
    "footprint": enums_pb2.KOT_PCB_FOOTPRINT,
    "pad": enums_pb2.KOT_PCB_PAD,
    "shape": enums_pb2.KOT_PCB_SHAPE,
    "text": enums_pb2.KOT_PCB_TEXT,
    "textbox": enums_pb2.KOT_PCB_TEXTBOX,
    "track": enums_pb2.KOT_PCB_TRACE,
    "via": enums_pb2.KOT_PCB_VIA,
    "arc": enums_pb2.KOT_PCB_ARC,
    "zone": enums_pb2.KOT_PCB_ZONE,
    "dimension": enums_pb2.KOT_PCB_DIMENSION,
}


def _pcb_context() -> tuple:
    """返回 (socket_url, ItemHeader)，两者来自同一个 pcbnew 进程。

    注意：KiCad 多进程架构下，pcbnew 的 socket 是 api-<pid>.sock，
    不能使用默认的 api.sock（那是 kicad 主进程，没有 CreateItems handler）。
    """
    url, docs = find_document_socket(DOCTYPE_PCB)
    if url is None:
        raise RuntimeError(
            "没有可用的 PCB 进程。请先启动 KiCad 的 pcbnew 并打开一个 .kicad_pcb 文件。"
        )
    header = base_types_pb2.ItemHeader()
    header.document.CopyFrom(docs[0])
    return url, header


def _check_create_resp(resp) -> None:
    if resp.status != 1:
        raise RuntimeError(f"KiCad 返回整体状态码 {resp.status}")
    for ci in resp.created_items:
        if ci.status.code != 1:
            raise RuntimeError(
                f"创建元素失败 (code={ci.status.code}): {ci.status.error_message}"
            )


def kicad_pcb_add_text(
    text: str,
    x_mm: float,
    y_mm: float,
    layer: str = "f.silkscreen",
    height_mm: float = 2.0,
) -> str:
    """在 PCB 上创建一个文本元素（BoardText）。

    Args:
        text: 文本内容。
        x_mm: 文本位置的 X 坐标（毫米）。
        y_mm: 文本位置的 Y 坐标（毫米）。
        layer: 所在层，如 "f.silkscreen" / "b.cu" / "f.cu"。
        height_mm: 字高（毫米）。
    """
    if layer.lower() not in LAYERS:
        raise ValueError(f"不支持的层: {layer}，可选: {sorted(LAYERS)}")

    bt = board_types_pb2.BoardText()
    bt.layer = LAYERS[layer.lower()]
    bt.text.position.x_nm = int(x_mm * MM)
    bt.text.position.y_nm = int(y_mm * MM)
    bt.text.attributes.size.x_nm = int(height_mm * MM)
    bt.text.attributes.size.y_nm = int(height_mm * MM)
    bt.text.text = text

    url, header = _pcb_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [bt])

    _check_create_resp(resp)
    return f"已在 {layer} 层 ({x_mm}mm, {y_mm}mm) 创建文本 '{text}'"


def kicad_pcb_add_track(
    x1_mm: float,
    y1_mm: float,
    x2_mm: float,
    y2_mm: float,
    width_mm: float = 0.25,
    layer: str = "f.cu",
) -> str:
    """在 PCB 上创建一条走线（Track 段）。

    Args:
        x1_mm, y1_mm: 起点坐标（毫米）。
        x2_mm, y2_mm: 终点坐标（毫米）。
        width_mm: 线宽（毫米）。
        layer: 所在层，如 "f.cu" / "b.cu"。
    """
    if layer.lower() not in LAYERS:
        raise ValueError(f"不支持的层: {layer}，可选: {sorted(LAYERS)}")

    t = board_types_pb2.Track()
    t.start.x_nm = int(x1_mm * MM)
    t.start.y_nm = int(y1_mm * MM)
    t.end.x_nm = int(x2_mm * MM)
    t.end.y_nm = int(y2_mm * MM)
    t.width.value_nm = int(width_mm * MM)
    t.layer = LAYERS[layer.lower()]

    url, header = _pcb_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [t])

    _check_create_resp(resp)
    return (
        f"已在 {layer} 层创建走线: ({x1_mm},{y1_mm})mm -> ({x2_mm},{y2_mm})mm, "
        f"宽 {width_mm}mm"
    )


def kicad_get_pcb_items(item_types: str = "footprint,text,track,via") -> str:
    """查询 PCB 上已有的元素，返回每种类型的数量。

    Args:
        item_types: 逗号分隔的对象类型，可选值: footprint,pad,shape,text,textbox,
            track,via,arc,zone,dimension。
    """
    wanted = []
    for name in (n.strip().lower() for n in item_types.split(",") if n.strip()):
        if name not in ITEM_TYPES:
            raise ValueError(f"不支持的对象类型: {name}，可选: {sorted(ITEM_TYPES)}")
        wanted.append(ITEM_TYPES[name])

    url, header = _pcb_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.get_items(header, wanted)

    counts: dict = {}
    for item in resp.items:
        counts[item.type_url] = counts.get(item.type_url, 0) + 1

    if not counts:
        return "PCB 上没有匹配的元素。"
    lines = [f"PCB 元素统计 ({sum(counts.values())} 个):"]
    for url, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"  - {url.split('/')[-1]}: {n}")
    return "\n".join(lines)


ALL_TOOLS = [
    kicad_pcb_add_text,
    kicad_pcb_add_track,
    kicad_get_pcb_items,
]
