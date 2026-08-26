"""快速验证编译版 eeschema 的原理图 API（文本/连线/符号创建）。"""
import sys
sys.path.insert(0, '/media/luskyle/DATA/project/kicad-mcp/kicad-mcp-python/src')

from kicad_mcp.client import (
    DOCTYPE_SCHEMATIC, KiCadClient, find_document_socket, make_document_specifier,
)
from kicad_mcp.proto.common.types import base_types_pb2
from kicad_mcp.proto.schematic import schematic_types_pb2

MM = 1_000_000

print("1) 发现原理图 socket ...")
url, docs = find_document_socket(DOCTYPE_SCHEMATIC)
print("   socket:", url)
for d in docs:
    print("   doc:", d)

if url is None:
    print("!! 未找到原理图进程，退出")
    sys.exit(1)

header = base_types_pb2.ItemHeader()
header.document.CopyFrom(docs[0])

with KiCadClient(url, client_name="kicad-mcp") as kc:
    # 注意：eeschema 只有 SCH handler，无 common handler（Ping/GetVersion 属 kicad 主进程）
    print("\n2) (跳过 get_version —— eeschema 无 common handler)")

    print("\n3) 创建文本 ...")
    t = schematic_types_pb2.Text()
    t.text.position.x_nm = int(120 * MM)
    t.text.position.y_nm = int(80 * MM)
    t.text.attributes.size.x_nm = int(2.54 * MM)
    t.text.attributes.size.y_nm = int(2.54 * MM)
    t.text.text = "Hello from MCP patched KiCad 10"
    resp = kc.create_items(header, [t])
    print("   整体状态:", resp.status)
    for ci in resp.created_items:
        print("   status code:", ci.status.code,
              ci.status.error_message or "", "| item type:",
              ci.item.type_url.split('/')[-1])

    print("\n4) 创建连线 (wire) ...")
    line = schematic_types_pb2.Line()
    line.start.x_nm = int(100 * MM)
    line.start.y_nm = int(100 * MM)
    line.end.x_nm = int(140 * MM)
    line.end.y_nm = int(100 * MM)
    line.layer = schematic_types_pb2.SchematicLayer.SL_WIRE
    resp = kc.create_items(header, [line])
    print("   整体状态:", resp.status)
    for ci in resp.created_items:
        print("   status code:", ci.status.code,
              ci.status.error_message or "", "| item type:",
              ci.item.type_url.split('/')[-1])

    print("\n5) 查询已创建元素 ...")
    got = kc.get_items(header, [1, 3])  # 1=text, 3=line (按 proto 定义)
    print("   返回 items:", len(got.items))

print("\nDONE")
