"""KiCad MCP 原理图工具：创建/查询/更新/删除原理图元素。

⚠️ 这些工具依赖 KiCad 源码补丁（见仓库 PATCH 说明：SchematicLayer 枚举、
TypeNameFromAny schematic 映射、SCH_TEXT/SCH_SYMBOL/Label 序列化、符号库加载、
GetItems/SaveDocument handler、多元素创建修复）。
未打补丁的 KiCad 10.0.5 上，创建原理图元素会导致 eeschema 段错误崩溃！
"""

from __future__ import annotations

from typing import Optional

from ..client import (
    DOCTYPE_SCHEMATIC,
    KiCadClient,
    find_document_socket,
)
from ..proto.common.types import base_types_pb2, enums_pb2
from ..proto.schematic import schematic_types_pb2

# 原理图内部单位: SCH_IU_PER_MM = 1e4 (1 IU = 100nm)。KiCad API 的 x_nm 字段
# 实际存的就是内部 IU（PackVector2/UnpackVector2 不做单位换算），因此原理图
# 坐标换算 1mm = 1e4，而不是 PCB 的 1e6（PCB_IU_PER_MM = 1e6）。
MM = 10_000

# 元素类型名 -> KiCadObjectType 枚举（GetItems 查询用）
KOT_MAP = {
    "text": enums_pb2.KOT_SCH_TEXT,
    "symbol": enums_pb2.KOT_SCH_SYMBOL,
    "line": enums_pb2.KOT_SCH_LINE,
    "local_label": enums_pb2.KOT_SCH_LABEL,
    "global_label": enums_pb2.KOT_SCH_GLOBAL_LABEL,
    "hier_label": enums_pb2.KOT_SCH_HIER_LABEL,
    "directive_label": enums_pb2.KOT_SCH_DIRECTIVE_LABEL,
}

LABEL_TYPE_MAP = {
    "global": schematic_types_pb2.GlobalLabel,
    "local": schematic_types_pb2.LocalLabel,
    "hier": schematic_types_pb2.HierarchicalLabel,
    "directive": schematic_types_pb2.DirectiveLabel,
}


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
    orientation_degrees: int = 0,
) -> str:
    """在原理图上放置一个符号（SCH_SYMBOL）。

    Args:
        lib_nickname: 符号库昵称（如 "Device"）。
        entry_name: 符号名（如 "R" / "C"）。
        x_mm, y_mm: 符号位置（毫米）。
        reference: 可选，参考位号（如 "R1"）。
        value: 可选，值（如 "10k"）。
        orientation_degrees: 旋转角度（0/90/180/270，默认 0）。

    注意: 需要已打补丁的 KiCad（10.0.5 会崩溃）。
    """
    symbol = schematic_types_pb2.Symbol()
    symbol.position.x_nm = int(x_mm * MM)
    symbol.position.y_nm = int(y_mm * MM)
    symbol.lib_id.library_nickname = lib_nickname
    symbol.lib_id.entry_name = entry_name
    symbol.orientation_degrees = int(orientation_degrees)
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
        + (f" (旋转 {orientation_degrees}°)" if orientation_degrees else "")
    )


def kicad_sch_add_label(
    label_type: str,
    text: str,
    x_mm: float,
    y_mm: float,
    height_mm: float = 2.54,
) -> str:
    """在原理图上创建一个网络标签（Global/Local/Hier/Directive）。

    Args:
        label_type: 标签类型 "global" | "local" | "hier" | "directive"。
        text: 标签文本（即网络名，如 "VCC" / "NET_A"）。
        x_mm, y_mm: 标签位置（毫米）。
        height_mm: 字高（毫米）。

    需要已打补丁的 KiCad（Label 文本序列化补丁）。
    """
    if label_type.lower() not in LABEL_TYPE_MAP:
        raise ValueError(f"不支持的标签类型: {label_type}，可选: {sorted(LABEL_TYPE_MAP)}")

    label = LABEL_TYPE_MAP[label_type.lower()]()
    label.position.x_nm = int(x_mm * MM)
    label.position.y_nm = int(y_mm * MM)
    label.text.text.text = text
    label.text.text.position.x_nm = int(x_mm * MM)
    label.text.text.position.y_nm = int(y_mm * MM)
    label.text.text.attributes.size.x_nm = int(height_mm * MM)
    label.text.text.attributes.size.y_nm = int(height_mm * MM)

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.create_items(header, [label])

    _check_create_resp(resp)
    return f"已在原理图 ({x_mm}mm, {y_mm}mm) 创建 {label_type} 标签 '{text}'"


def _fmt_any(any_item) -> str:
    """把 GetItems 返回的 Any 解包成一行可读描述。"""
    if any_item.Is(schematic_types_pb2.Text.DESCRIPTOR):
        t = schematic_types_pb2.Text()
        any_item.Unpack(t)
        return (f"Text id={t.id.value} '{t.text.text}' "
                f"@({t.text.position.x_nm / MM:.1f},{t.text.position.y_nm / MM:.1f})mm")
    if any_item.Is(schematic_types_pb2.Symbol.DESCRIPTOR):
        s = schematic_types_pb2.Symbol()
        any_item.Unpack(s)
        fields = {f.name: f.value for f in s.fields}
        return (f"Symbol id={s.id.value} {s.lib_id.library_nickname}:{s.lib_id.entry_name} "
                f"ref={fields.get('Reference', '')} value={fields.get('Value', '')} "
                f"@({s.position.x_nm / MM:.1f},{s.position.y_nm / MM:.1f})mm")
    if any_item.Is(schematic_types_pb2.Line.DESCRIPTOR):
        ln = schematic_types_pb2.Line()
        any_item.Unpack(ln)
        layer = {1: 'wire', 2: 'bus', 3: 'notes'}.get(ln.layer, str(ln.layer))
        return (f"Line id={ln.id.value} layer={layer} "
                f"({ln.start.x_nm / MM:.1f},{ln.start.y_nm / MM:.1f})->"
                f"({ln.end.x_nm / MM:.1f},{ln.end.y_nm / MM:.1f})mm")
    for proto_cls, kind in [
        (schematic_types_pb2.GlobalLabel, 'GlobalLabel'),
        (schematic_types_pb2.LocalLabel, 'LocalLabel'),
        (schematic_types_pb2.HierarchicalLabel, 'HierLabel'),
        (schematic_types_pb2.DirectiveLabel, 'DirectiveLabel'),
    ]:
        if any_item.Is(proto_cls.DESCRIPTOR):
            l = proto_cls()
            any_item.Unpack(l)
            return (f"{kind} id={l.id.value} '{l.text.text.text}' "
                    f"@({l.position.x_nm / MM:.1f},{l.position.y_nm / MM:.1f})mm")
    return f"<{any_item.type_url.split('/')[-1]}>"


def kicad_sch_get_items(item_types: str = "text,symbol,line,label") -> str:
    """查询原理图中的元素（读回现状，供规划/校验用）。

    Args:
        item_types: 逗号分隔的类型，可选: text / symbol / line / local_label /
            global_label / hier_label / directive_label；"label" 表示全部标签。

    Returns:
        每行一个元素的描述（含 KIID，供更新/删除使用）。
    """
    kots = []
    for raw in item_types.split(','):
        t = raw.strip()
        if t == "label":
            kots += [enums_pb2.KOT_SCH_LABEL, enums_pb2.KOT_SCH_GLOBAL_LABEL,
                     enums_pb2.KOT_SCH_HIER_LABEL, enums_pb2.KOT_SCH_DIRECTIVE_LABEL]
        elif t in KOT_MAP:
            kots.append(KOT_MAP[t])
    if not kots:
        raise ValueError(f"没有可用的元素类型: {item_types}")

    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        got = kc.get_items(header, kots)

    lines = [_fmt_any(a) for a in got.items]
    return "\n".join(lines) if lines else "（原理图中没有匹配的元素）"


def kicad_sch_update_text(
    item_id: str,
    text: Optional[str] = None,
    x_mm: Optional[float] = None,
    y_mm: Optional[float] = None,
) -> str:
    """更新一个文本元素的内容和/或位置（按 GetItems 返回的 id）。

    Args:
        item_id: 目标文本的 KIID（来自 kicad_sch_get_items）。
        text: 新内容（不传则不改）。
        x_mm, y_mm: 新位置（不传则不改）。
    """
    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        got = kc.get_items(header, [KOT_MAP["text"]])
        for a in got.items:
            if not a.Is(schematic_types_pb2.Text.DESCRIPTOR):
                continue
            t = schematic_types_pb2.Text()
            a.Unpack(t)
            if t.id.value != item_id:
                continue
            if text is not None:
                t.text.text = text
            if x_mm is not None:
                t.text.position.x_nm = int(x_mm * MM)
            if y_mm is not None:
                t.text.position.y_nm = int(y_mm * MM)
            resp = kc.update_items(header, [t])
            for r in resp.updated_items:
                if r.status.code != 1:
                    raise RuntimeError(f"更新失败: {r.status.error_message}")
            return f"已更新文本 {item_id[:12]}"
        raise RuntimeError(f"未找到 id={item_id} 的文本元素")


def kicad_sch_delete_item(item_id: str) -> str:
    """按 KIID 删除原理图中的一个元素。

    Args:
        item_id: 元素 KIID（来自 kicad_sch_get_items）。
    """
    url, header = _sch_context()
    with KiCadClient(url, client_name="kicad-mcp") as kc:
        resp = kc.delete_items(header, [item_id])

    for r in resp.deleted_items:
        if r.id.value == item_id:
            if r.status == 1:   # IDS_OK
                return f"已删除元素 {item_id[:12]}"
            return f"删除失败: 状态 {r.status}"
    return f"未找到 id={item_id}（或已被删除）"


ALL_TOOLS = [
    kicad_sch_add_text,
    kicad_sch_add_line,
    kicad_sch_add_symbol,
    kicad_sch_add_label,
    kicad_sch_get_items,
    kicad_sch_update_text,
    kicad_sch_delete_item,
]
