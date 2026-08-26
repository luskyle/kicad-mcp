"""保存当前原理图文档。"""
import sys
sys.path.insert(0, '/media/luskyle/DATA/project/kicad-mcp/kicad-mcp-python/src')

from kicad_mcp.client import DOCTYPE_SCHEMATIC, KiCadClient, find_document_socket

url, docs = find_document_socket(DOCTYPE_SCHEMATIC)
print("socket:", url)
if url is None:
    sys.exit(1)

with KiCadClient(url, client_name="kicad-mcp") as kc:
    for d in docs:
        print("保存:", d.board_filename)
        kc.save_document(d)
print("saved OK")
