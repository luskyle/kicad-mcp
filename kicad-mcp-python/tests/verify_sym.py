"""验证符号（Symbol）创建 —— Device 库 R 电阻。"""
import sys
sys.path.insert(0, '/media/luskyle/DATA/project/kicad-mcp/kicad-mcp-python/src')

from kicad_mcp.client import (
    DOCTYPE_SCHEMATIC, KiCadClient, find_document_socket,
)
from kicad_mcp.proto.common.types import base_types_pb2
from kicad_mcp.proto.schematic import schematic_types_pb2

MM = 1_000_000

url, docs = find_document_socket(DOCTYPE_SCHEMATIC)
print("socket:", url)
if url is None:
    sys.exit(1)

header = base_types_pb2.ItemHeader()
header.document.CopyFrom(docs[0])

with KiCadClient(url, client_name="kicad-mcp") as kc:
    print("创建符号 Device:R ...")
    sym = schematic_types_pb2.Symbol()
    sym.position.x_nm = int(130 * MM)
    sym.position.y_nm = int(90 * MM)
    sym.lib_id.library_nickname = "Device"
    sym.lib_id.entry_name = "R"
    f = sym.fields.add(); f.name = "Reference"; f.value = "R1"
    f = sym.fields.add(); f.name = "Value"; f.value = "10k"

    resp = kc.create_items(header, [sym])
    print("整体状态:", resp.status)
    for ci in resp.created_items:
        print("status code:", ci.status.code,
              ci.status.error_message or "", "| item type:",
              ci.item.type_url.split('/')[-1])
        if ci.item.Is(schematic_types_pb2.Symbol.DESCRIPTOR):
            created = schematic_types_pb2.Symbol()
            ci.item.Unpack(created)
            print("   created symbol lib_id:",
                  created.lib_id.library_nickname + ":" + created.lib_id.entry_name,
                  "fields:", [(f.name, f.value) for f in created.fields])

print("\nDONE")
