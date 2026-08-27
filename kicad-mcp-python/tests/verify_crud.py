"""验证原理图 CRUD：GetItems / UpdateItems / DeleteItems（需编译版 eeschema + GetItems 补丁）。"""
import sys
sys.path.insert(0, '/media/luskyle/DATA/project/kicad-mcp/kicad-mcp-python/src')

from kicad_mcp.client import (
    DOCTYPE_SCHEMATIC, KiCadClient, find_document_socket,
)
from kicad_mcp.proto.common.types import base_types_pb2
from kicad_mcp.proto.common.types import enums_pb2
from kicad_mcp.proto.schematic import schematic_types_pb2

MM = 1_000_000
KOT_SCH_TEXT = enums_pb2.KOT_SCH_TEXT
KOT_SCH_SYMBOL = enums_pb2.KOT_SCH_SYMBOL
KOT_SCH_LINE = enums_pb2.KOT_SCH_LINE


def make_text(content, x, y):
    t = schematic_types_pb2.Text()
    t.text.position.x_nm = int(x * MM)
    t.text.position.y_nm = int(y * MM)
    t.text.attributes.size.x_nm = int(2.54 * MM)
    t.text.attributes.size.y_nm = int(2.54 * MM)
    t.text.text = content
    return t


url, docs = find_document_socket(DOCTYPE_SCHEMATIC)
print("socket:", url)
if url is None:
    sys.exit(1)

header = base_types_pb2.ItemHeader()
header.document.CopyFrom(docs[0])

with KiCadClient(url, client_name="kicad-mcp") as kc:
    # 1) 创建两个文本
    print("\n== 1) 创建文本 ==")
    resp = kc.create_items(header, [make_text("CRUD-TEST-A", 200, 80), make_text("CRUD-TEST-B", 200, 85)])
    print("   整体:", resp.status, "| created:", len(resp.created_items))

    # 2) GetItems 读回全部文本
    print("\n== 2) GetItems(KOT_SCH_TEXT) ==")
    got = kc.get_items(header, [KOT_SCH_TEXT])
    print("   返回 items:", len(got.items), "| status:", got.status)
    texts = []
    for any_item in got.items:
        if any_item.Is(schematic_types_pb2.Text.DESCRIPTOR):
            t = schematic_types_pb2.Text()
            any_item.Unpack(t)
            texts.append(t)
            print(f"   - id={t.id.value[:12]}... text='{t.text.text}' "
                  f"pos=({t.text.position.x_nm/MM:.1f},{t.text.position.y_nm/MM:.1f})mm")
    assert any(t.text.text == "CRUD-TEST-A" for t in texts), "GetItems 未读回创建的文本!"

    # 3) UpdateItems：把 CRUD-TEST-A 内容改掉并移动位置
    print("\n== 3) UpdateItems ==")
    target = next(t for t in texts if t.text.text == "CRUD-TEST-A")
    new_t = schematic_types_pb2.Text()
    new_t.CopyFrom(target)
    new_t.text.text = "CRUD-TEST-A-MODIFIED"
    new_t.text.position.x_nm = int(210 * MM)
    new_t.text.position.y_nm = int(80 * MM)
    resp = kc.update_items(header, [new_t])
    print("   整体:", resp.status, "| updated:", len(resp.updated_items))
    for r in resp.updated_items:
        print("   status code:", r.status.code, r.status.error_message or "")

    # 4) GetItems 确认更新
    print("\n== 4) GetItems 确认更新 ==")
    got = kc.get_items(header, [KOT_SCH_TEXT])
    all_texts = []
    for any_item in got.items:
        if any_item.Is(schematic_types_pb2.Text.DESCRIPTOR):
            t = schematic_types_pb2.Text()
            any_item.Unpack(t)
            all_texts.append(t)
            print(f"   - text='{t.text.text}' pos=({t.text.position.x_nm/MM:.1f},{t.text.position.y_nm/MM:.1f})mm")
    assert any(t.text.text == "CRUD-TEST-A-MODIFIED" for t in all_texts), "UpdateItems 未生效!"

    # 5) DeleteItems：删除 CRUD-TEST-A-MODIFIED
    print("\n== 5) DeleteItems ==")
    del_target = next(t for t in all_texts if t.text.text == "CRUD-TEST-A-MODIFIED")
    resp = kc.delete_items(header, [del_target.id.value])
    print("   整体:", resp.status, "| deleted:", len(resp.deleted_items))
    for r in resp.deleted_items:
        print("   status:", r.status, "| id:", r.id.value[:12])

    # 6) GetItems 确认删除
    print("\n== 6) GetItems 确认删除 ==")
    got = kc.get_items(header, [KOT_SCH_TEXT])
    remaining = []
    for any_item in got.items:
        if any_item.Is(schematic_types_pb2.Text.DESCRIPTOR):
            t = schematic_types_pb2.Text()
            any_item.Unpack(t)
            remaining.append(t.text.text)
    print("   剩余文本:", remaining)
    assert "CRUD-TEST-A-MODIFIED" not in remaining, "DeleteItems 未生效!"

print("\n[PASS] 原理图 CRUD（GetItems/UpdateItems/DeleteItems）全部验证通过")
