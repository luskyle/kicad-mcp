"""Save/reload quality gate for generated KiCad schematics."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from collections import Counter
from pathlib import Path

from ..client import DOCTYPE_SCHEMATIC, KiCadClient, find_document_socket
from ..runtime import resolve_kicad_runtime
from ..symbols import parse_sexpr
from .quality import _export_netlist
from .schematic import _current_sch_path, _sch_context

_OBJECT_TAGS = {
    "symbol", "wire", "bus", "bus_entry", "junction", "label",
    "global_label", "hierarchical_label", "text", "text_box", "shape",
    "sheet", "no_connect",
}


def _nodes(node, tag: str):
    if isinstance(node, list):
        if node and node[0] == tag:
            yield node
        for child in node:
            yield from _nodes(child, tag)


def _root(path: Path) -> list:
    parsed = parse_sexpr(path.read_text(encoding="utf-8"))
    if len(parsed) != 1 or not parsed[0] or parsed[0][0] != "kicad_sch":
        raise RuntimeError(f"无效的 KiCad 原理图: {path}")
    return parsed[0]


def _atom(node: list, tag: str) -> str:
    for child in node:
        if isinstance(child, list) and child and child[0] == tag and len(child) > 1:
            return str(child[1])
    return ""


def _sheet_files(path: Path, root: list) -> list[Path]:
    files = []
    for sheet in (node for node in root[1:] if isinstance(node, list) and node[:1] == ["sheet"]):
        for prop in (node for node in sheet if isinstance(node, list) and node[:1] == ["property"]):
            if len(prop) > 2 and prop[1] == "Sheetfile":
                files.append((path.parent / str(prop[2])).resolve())
    return files


def semantic_snapshot(schematic: str | Path) -> dict:
    """Return a stable semantic snapshot for a complete schematic hierarchy."""
    root_path = Path(schematic).resolve()
    pending = [root_path]
    seen: set[Path] = set()
    sheets = []

    while pending:
        path = pending.pop(0)
        if path in seen:
            continue
        if not path.is_file():
            raise RuntimeError(f"层级原理图不存在: {path}")
        seen.add(path)
        root = _root(path)
        counts = Counter(
            str(node[0]) for node in root[1:]
            if isinstance(node, list) and node and node[0] in _OBJECT_TAGS
        )
        instances = sorted(
            (str(node[1]), _atom(node, "page"))
            for node in _nodes(root, "path") if len(node) > 1
        )
        uuids = sorted(str(node[1]) for node in _nodes(root, "uuid") if len(node) > 1)
        sheets.append({
            "file": path.name,
            "root_uuid": _atom(root, "uuid"),
            "uuids": uuids,
            "instances": instances,
            "object_counts": dict(sorted(counts.items())),
        })
        pending.extend(_sheet_files(path, root))

    nets = _export_netlist(str(root_path))
    connections = sorted(
        (
            str(net["name"]),
            tuple(sorted((str(node["ref"]), str(node["pin"])) for node in net["nodes"])),
        )
        for net in nets
    )
    return {"sheets": sorted(sheets, key=lambda item: item["file"]), "connections": connections}


def _wait_for_document(path: Path, timeout: float) -> tuple[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        url, docs = find_document_socket(DOCTYPE_SCHEMATIC)
        for doc in docs:
            candidate = Path(doc.project.path) / doc.board_filename
            if candidate.resolve() == path:
                return url, doc
        time.sleep(0.1)
    raise RuntimeError(f"仓库 Eeschema 未在 {timeout:g} 秒内打开原理图: {path}")


def _wait_for_document_closed(path: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, docs = find_document_socket(DOCTYPE_SCHEMATIC)
        if not any(
            (Path(doc.project.path) / doc.board_filename).resolve() == path
            for doc in docs
        ):
            return
        time.sleep(0.1)
    raise RuntimeError(f"Eeschema 未在 {timeout:g} 秒内关闭原理图: {path}")


def _process_exists(process_id: int) -> bool:
    if process_id <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(process_id, 0)
        return True
    except OSError:
        return False


def _finish_closed_process(process_id: int, timeout: float = 2) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _process_exists(process_id):
        time.sleep(0.05)
    if _process_exists(process_id):
        if os.name == "nt":
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, process_id)
            if not handle:
                raise RuntimeError(f"无法打开 Eeschema 进程进行终止: PID {process_id}")
            try:
                if not ctypes.windll.kernel32.TerminateProcess(handle, 0):
                    raise RuntimeError(f"无法终止 Eeschema 进程: PID {process_id}")
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        else:
            os.kill(process_id, signal.SIGTERM)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and _process_exists(process_id):
            time.sleep(0.05)
        if _process_exists(process_id):
            raise RuntimeError(f"Eeschema 进程终止超时: PID {process_id}")


def kicad_sch_reload_gate(rounds: int = 2, timeout_seconds: float = 30) -> str:
    """Save, close and reopen a schematic, rejecting repairs or semantic drift."""
    if rounds < 1:
        raise ValueError("rounds 必须至少为 1")

    path = Path(_current_sch_path()).resolve()
    runtime = resolve_kicad_runtime()
    initial_url, initial_header = _sch_context()
    with KiCadClient(initial_url, client_name="kicad-mcp") as client:
        client.save_document(initial_header.document)
    baseline = semantic_snapshot(path)
    results = []

    for round_number in range(1, rounds + 1):
        url, header = _sch_context()
        with KiCadClient(url, client_name="kicad-mcp") as client:
            process_id = int(client.get_schematic_state(header.document).process_id)
            client.save_document(header.document)
            client.close_document(header.document)

        _wait_for_document_closed(path, timeout_seconds)
        _finish_closed_process(process_id)
        subprocess.Popen(
            [str(runtime.eeschema), str(path)],
            cwd=str(path.parent),
            env=runtime.cli_env(),
        )
        reopened_url, document = _wait_for_document(path, timeout_seconds)
        with KiCadClient(reopened_url, client_name="kicad-mcp") as client:
            state = client.get_schematic_state(document)
            if state.load_had_repairs:
                raise RuntimeError(f"第 {round_number} 轮失败: KiCad 加载时自动修复了原理图")
            if state.content_modified:
                raise RuntimeError(f"第 {round_number} 轮失败: 重开后存在未保存修改")
            client.save_document(document)

        current = semantic_snapshot(path)
        if current != baseline:
            report = path.with_suffix(".reload-diff.json")
            report.write_text(
                json.dumps({"before": baseline, "after": current}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            raise RuntimeError(f"第 {round_number} 轮失败: 语义快照发生变化，详情: {report}")
        results.append(f"第 {round_number} 轮通过")

    return f"✅ 重载门禁通过: {', '.join(results)}；加载无修复且语义快照稳定"


ALL_TOOLS = [kicad_sch_reload_gate]