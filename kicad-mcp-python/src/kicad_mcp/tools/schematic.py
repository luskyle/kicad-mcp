"""KiCad MCP 原理图工具：创建文本/连线/符号。

⚠️ 这些工具依赖 KiCad 源码补丁（见仓库 PATCH 说明：SchematicLayer 枚举、
TypeNameFromAny schematic 映射、SCH_TEXT/SCH_SYMBOL 序列化、符号库加载）。
未打补丁的 KiCad 10.0.5 上，创建原理图元素会导致 eeschema 段错误崩溃！
"""

from __future__ import annotations

from typing import Optional

from ..client import (
    DOCTYPE_SCHEMATIC,
    KiCadClient,
    find_document_socket,
)
from ..proto.common.types import base_types_pb2
from ..proto.schematic import schematic_types_pb2

MM = 1_000_000


def _sch_context() -> tuple:
    url, docs = find_document_socket(DOCTYPE_SCHEMATIC)
    if url is None:
        raise RuntimeError(
            "没有可用的原理图进程。请先启动 KiCad 的 eeschema 并打开一个 .kicad_sch 文件。"
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


def kicad_sch_add_text(
    text: str,
    x_mm: float,
    y_mm: float,
    height_mm: float = 2.54,
) -> str:
    """在原理图上创建一个文本注释（SCH_TEXT）。

    Args:
        text: 文本内容。
        x_mm, y_mm: 文本位置（毫米）。
        height_mm: 字高（毫米）。

    注意: 需要已打补丁的 KiCad（10.0.5 会崩溃）。
    """
    sch_text = schematic_types_pb2.Text()
    sch_text.text.position.x_nm = int(x_mm * MM)
    sch_text.text.position.y_nm = int(y_mm * MM)
    sch_text.text.attributes.size.x_nm = int(height_mm * MM)
    sch_text.text.attributes.size.y_nm = int(height_mm * MM)
    sch_text.text.text = text

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [sch_text])

    _check_create_resp(resp)
    return f"已在原理图 ({x_mm}mm, {y_mm}mm) 创建文本 '{text}'"


def kicad_sch_add_line(
    x1_mm: float,
    y1_mm: float,
    x2_mm: float,
    y2_mm: float,
    layer: str = "wire",
) -> str:
    """在原理图上创建一条连线/图形线（SCH_LINE）。

    Args:
        x1_mm, y1_mm: 起点（毫米）。
        x2_mm, y2_mm: 终点（毫米）。
        layer: 层，"wire" | "bus" | "notes"。

    注意: 需要已打补丁的 KiCad（10.0.5 会崩溃）。
    """
    layers = {"wire": schematic_types_pb2.SL_WIRE,
              "bus": schematic_types_pb2.SL_BUS,
              "notes": schematic_types_pb2.SL_NOTES}
    if layer.lower() not in layers:
        raise ValueError(f"不支持的层: {layer}，可选: {sorted(layers)}")

    line = schematic_types_pb2.Line()
    line.start.x_nm = int(x1_mm * MM)
    line.start.y_nm = int(y1_mm * MM)
    line.end.x_nm = int(x2_mm * MM)
    line.end.y_nm = int(y2_mm * MM)
    line.layer = layers[layer.lower()]

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [line])

    _check_create_resp(resp)
    return (
        f"已在原理图 {layer} 层创建连线: ({x1_mm},{y1_mm})mm -> ({x2_mm},{y2_mm})mm"
    )


def kicad_sch_add_symbol(
    lib_nickname: str,
    entry_name: str,
    x_mm: float,
    y_mm: float,
    reference: Optional[str] = None,
    value: Optional[str] = None,
) -> str:
    """在原理图上放置一个符号（SCH_SYMBOL）。

    Args:
        lib_nickname: 符号库昵称（如 "Device"）。
        entry_name: 符号名（如 "R" / "C"）。
        x_mm, y_mm: 符号位置（毫米）。
        reference: 可选，参考位号（如 "R1"）。
        value: 可选，值（如 "10k"）。

    注意: 需要已打补丁的 KiCad（10.0.5 会崩溃）。
    """
    symbol = schematic_types_pb2.Symbol()
    symbol.position.x_nm = int(x_mm * MM)
    symbol.position.y_nm = int(y_mm * MM)
    symbol.lib_id.library_nickname = lib_nickname
    symbol.lib_id.entry_name = entry_name
    if reference:
        f = symbol.fields.add()
        f.name = "Reference"
        f.value = reference
    if value:
        f = symbol.fields.add()
        f.name = "Value"
        f.value = value

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [symbol])

    _check_create_resp(resp)
    return (
        f"已在原理图 ({x_mm}mm, {y_mm}mm) 放置符号 {lib_nickname}:{entry_name}"
        + (f" (ref={reference})" if reference else "")
    )


ALL_TOOLS = [
    kicad_sch_add_text,
    kicad_sch_add_line,
    kicad_sch_add_symbol,
]
