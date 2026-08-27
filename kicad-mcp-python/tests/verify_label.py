"""验证原理图网络标签（GlobalLabel/LocalLabel）创建 + 读回（含文本）。

需要编译版 eeschema（Label 序列化补丁）+ GetItems 补丁。
"""
import sys
sys.path.insert(0, '/media/luskyle/DATA/project/kicad-mcp/kicad-mcp-python/src')

from kicad_mcp.client import (
    DOCTYPE_SCHEMATIC, KiCadClient, find_document_socket,
)
from kicad_mcp.proto.common.types import base_types_pb2, enums_pb2
from kicad_mcp.proto.schematic import schematic_types_pb2

MM = 1_000_000


def mk_label(msg_type, name, x, y):
    l = msg_type()
    l.position.x_nm = int(x * MM)
    l.position.y_nm = int(y * MM)
    l.text.text.text = name
    l.text.text.position.x_nm = int(x * MM)
    l.text.text.position.y_nm = int(y * MM)
    l.text.text.attributes.size.x_nm = int(2.54 * MM)
    l.text.text.attributes.size.y_nm = int(2.54 * MM)
    return l


url, docs = find_document_socket(DOCTYPE_SCHEMATIC)
print("socket:", url)
if url is None:
    sys.exit(1)

header = base_types_pb2.ItemHeader()
header.document.CopyFrom(docs[0])

with KiCadClient(url, client_name="kicad-mcp") as kc:
    print("\n== 1) 创建 GlobalLabel + LocalLabel ==")
    resp = kc.create_items(header, [
        mk_label(schematic_types_pb2.GlobalLabel, "VCC_MCP", 300, 80),
        mk_label(schematic_types_pb2.LocalLabel, "NET_A", 300, 100),
    ])
    print("   created:", len(resp.created_items))
    for ci in resp.created_items:
        print("   code:", ci.status.code, ci.status.error_message or "",
              "|", ci.item.type_url.split('/')[-1])

    print("\n== 2) GetItems 读回标签 ==")
    got = kc.get_items(header, [enums_pb2.KOT_SCH_GLOBAL_LABEL, enums_pb2.KOT_SCH_LABEL])
    print("   返回:", len(got.items))
    labels = {}
    for a in got.items:
        if a.Is(schematic_types_pb2.GlobalLabel.DESCRIPTOR):
            x = schematic_types_pb2.GlobalLabel(); a.Unpack(x)
            labels.setdefault("global", []).append(x.text.text.text)
            print(f"   GLOBAL: '{x.text.text.text}' id={x.id.value[:12]} pos=({x.position.x_nm/MM:.0f},{x.position.y_nm/MM:.0f})")
        elif a.Is(schematic_types_pb2.LocalLabel.DESCRIPTOR):
            x = schematic_types_pb2.LocalLabel(); a.Unpack(x)
            labels.setdefault("local", []).append(x.text.text.text)
            print(f"   LOCAL:  '{x.text.text.text}' id={x.id.value[:12]} pos=({x.position.x_nm/MM:.0f},{x.position.y_nm/MM:.0f})")

    assert "VCC_MCP" in labels.get("global", []), "GlobalLabel 文本未读回!"
    assert "NET_A" in labels.get("local", []), "LocalLabel 文本未读回!"

print("\n[PASS] 标签创建 + 文本读回验证通过")
