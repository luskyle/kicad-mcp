"""KiCad MCP 基础工具：连通性、版本、文档查询/保存。"""

from __future__ import annotations

from typing import Optional

from ..client import (
    DOC_TYPE_NAMES,
    KiCadClient,
    make_document_specifier,
)


def _client() -> KiCadClient:
    """每次调用新建一个短连接（可靠，KiCad 可随时重启）。"""
    return KiCadClient(client_name="kicad-mcp")


def kicad_ping() -> str:
    """检查本机 KiCad API Server 是否可连接（即 KiCad 是否正在运行并启用了 API）。"""
    with _client() as kc:
        kc.ping()
        return "pong"


def kicad_get_version() -> str:
    """返回正在运行的 KiCad 版本号。"""
    with _client() as kc:
        return kc.get_version()


def _describe_doc(doc) -> str:
    parts = [DOC_TYPE_NAMES.get(doc.type, f"type={doc.type}")]
    which = doc.WhichOneof("identifier")
    if which == "board_filename":
        parts.append(f"file={doc.board_filename}")
    elif which == "sheet_path":
        parts.append(f"sheet={doc.sheet_path.path_human_readable}")
    elif which == "lib_id":
        parts.append(f"lib={doc.lib_id.library_nickname}:{doc.lib_id.entry_name}")
    if doc.HasField("project"):
        proj = doc.project
        if proj.name:
            parts.append(f"project={proj.name}")
    return " | ".join(parts)


def kicad_get_open_documents(doc_type: str = "schematic") -> str:
    """列出 KiCad 中当前打开的文档。

    Args:
        doc_type: 文档类型，取值 "schematic" | "pcb" | "symbol" | "footprint" | "project"。
    """
    rev = {v: k for k, v in DOC_TYPE_NAMES.items()}
    if doc_type not in rev:
        raise ValueError(f"不支持的文档类型: {doc_type}，可选 {sorted(rev)}")
    with _client() as kc:
        docs = kc.get_open_documents(rev[doc_type])
    if not docs:
        return f"当前没有打开的 {doc_type} 文档。"
    return "\n".join(_describe_doc(d) for d in docs)


def kicad_save_document(
    doc_type: str = "schematic",
    board_filename: Optional[str] = None,
    project_name: Optional[str] = None,
    project_path: Optional[str] = None,
) -> str:
    """保存 KiCad 中当前打开的某个文档。

    Args:
        doc_type: 文档类型，取值 "schematic" | "pcb" | "symbol" | "footprint" | "project"。
        board_filename: PCB 的文件名（如 "board.kicad_pcb"），用于定位 PCB 文档。
        project_name: 所属项目的名称（不带 .kicad_pro 后缀）。
        project_path: 项目所在目录的绝对路径。
    """
    rev = {v: k for k, v in DOC_TYPE_NAMES.items()}
    if doc_type not in rev:
        raise ValueError(f"不支持的文档类型: {doc_type}，可选 {sorted(rev)}")
    spec = make_document_specifier(
        rev[doc_type],
        board_filename=board_filename,
        project_name=project_name,
        project_path=project_path,
    )
    with _client() as kc:
        kc.save_document(spec)
    return f"已保存 {doc_type} 文档: {_describe_doc(spec)}"


ALL_TOOLS = [
    kicad_ping,
    kicad_get_version,
    kicad_get_open_documents,
    kicad_save_document,
]
