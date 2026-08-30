from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.client import (
    ApiResponse,
    KiCadClient,
    base_types_pb2,
    editor_commands_pb2,
)
from kicad_mcp.tools import reload


def test_client_get_schematic_state_unpacks_response(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = editor_commands_pb2.GetSchematicStateResponse(
        content_modified=True,
        load_had_repairs=False,
        process_id=123,
    )
    envelope = ApiResponse()
    envelope.message.Pack(expected)
    client = KiCadClient()
    monkeypatch.setattr(client, "_call", lambda request: envelope)

    state = client.get_schematic_state(base_types_pb2.DocumentSpecifier())

    assert state.content_modified is True
    assert state.load_had_repairs is False
    assert state.process_id == 123


def test_client_close_document_sends_close_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client = KiCadClient()
    requests = []
    monkeypatch.setattr(client, "_call", lambda request: requests.append(request))

    client.close_document(base_types_pb2.DocumentSpecifier())

    assert isinstance(requests[0], editor_commands_pb2.CloseDocument)


def test_semantic_snapshot_covers_hierarchy_and_connections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root.kicad_sch"
    child = tmp_path / "child.kicad_sch"
    root.write_text(
        '(kicad_sch (uuid "root") '
        '(sheet (uuid "sheet") (property "Sheetfile" "child.kicad_sch") '
        '(instances (project "demo" (path "/root" (page "2"))))) '
        '(sheet_instances (path "/" (page "1"))))',
        encoding="utf-8",
    )
    child.write_text(
        '(kicad_sch (uuid "child") (symbol (uuid "symbol")) '
        '(wire (uuid "wire")) (label "NET" (uuid "label")))',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        reload,
        "_export_netlist",
        lambda path: [{
            "name": "NET",
            "nodes": [
                {"ref": "R2", "pin": "2"},
                {"ref": "R1", "pin": "1"},
            ],
        }],
    )

    snapshot = reload.semantic_snapshot(root)

    assert [sheet["file"] for sheet in snapshot["sheets"]] == [
        "child.kicad_sch",
        "root.kicad_sch",
    ]
    assert snapshot["sheets"][0]["object_counts"] == {
        "label": 1,
        "symbol": 1,
        "wire": 1,
    }
    assert snapshot["sheets"][1]["instances"] == [("/", "1"), ("/root", "2")]
    assert snapshot["connections"] == [("NET", (("R1", "1"), ("R2", "2")))]


@pytest.mark.parametrize(
    ("load_had_repairs", "content_modified", "expected"),
    [
        (True, False, "自动修复"),
        (False, True, "未保存修改"),
        (False, False, "重载门禁通过"),
    ],
)
def test_reload_gate_reports_current_load_state(
    monkeypatch: pytest.MonkeyPatch,
    load_had_repairs: bool,
    content_modified: bool,
    expected: str,
) -> None:
    state = SimpleNamespace(
        load_had_repairs=load_had_repairs,
        content_modified=content_modified,
        process_id=0,
    )

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args) -> None:
            pass

        def get_schematic_state(self, document):
            return state

        def save_document(self, document) -> None:
            pass

        def close_document(self, document) -> None:
            pass

    monkeypatch.setattr(reload, "_current_sch_path", lambda: "sample.kicad_sch")
    monkeypatch.setattr(reload, "semantic_snapshot", lambda path: {"stable": True})
    monkeypatch.setattr(
        reload,
        "resolve_kicad_runtime",
        lambda: SimpleNamespace(
            eeschema="eeschema.exe",
            cli_env=lambda: {},
        ),
    )
    monkeypatch.setattr(
        reload,
        "_sch_context",
        lambda: ("ipc://test", SimpleNamespace(document=SimpleNamespace())),
    )
    monkeypatch.setattr(
        reload,
        "_wait_for_document",
        lambda path, timeout: ("ipc://test", SimpleNamespace()),
    )
    monkeypatch.setattr(reload, "_wait_for_document_closed", lambda path, timeout: None)
    monkeypatch.setattr(reload.subprocess, "Popen", lambda *args, **kwargs: None)
    monkeypatch.setattr(reload, "KiCadClient", FakeClient)

    if load_had_repairs or content_modified:
        with pytest.raises(RuntimeError, match=expected):
            reload.kicad_sch_reload_gate(rounds=1)
    else:
        assert expected in reload.kicad_sch_reload_gate(rounds=1)
