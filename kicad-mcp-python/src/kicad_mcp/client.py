"""KiCad API 客户端。

通过 nng(REQ/REP) + protobuf envelope 与运行中的 KiCad API Server 通信。

协议参考（本仓库源码）:
- 传输层: libs/kinng  (nng rep0, ipc://...)
- 消息:    api/proto/common/envelope.proto  (ApiRequest / ApiResponse)
- 分发:    common/api/api_handler.cpp       (按 Any.type_url 分发给 handler)
"""

from __future__ import annotations

import os
import platform
import tempfile
import sys
from pathlib import Path
from typing import Optional

# 生成的 protobuf 绑定根路径（gen_proto.sh 产物）
_PROTO_ROOT = Path(__file__).resolve().parent / "proto"
if str(_PROTO_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROTO_ROOT))

import pynng  # noqa: E402

from common.envelope_pb2 import (  # noqa: E402
    ApiRequest,
    ApiResponse,
    ApiStatusCode,
)
from common.commands import base_commands_pb2  # noqa: E402
from common.commands import editor_commands_pb2  # noqa: E402
from common.types import base_types_pb2  # noqa: E402


def default_socket_dir() -> str:
    """KiCad API socket 所在目录。"""
    if platform.system() == "Windows":
        return str(Path(tempfile.gettempdir()) / "kicad")
    return "/tmp/kicad"


def default_socket_url() -> str:
    """返回本机 KiCad API Server 的 nng socket URL。

    优先级: 环境变量 KICAD_API_SOCKET > 平台默认路径。
    KiCad 启动时会监听 /tmp/kicad/api.sock (Linux) 或 named pipe (Windows)。
    """
    env = os.environ.get("KICAD_API_SOCKET")
    if env:
        return env
    return f"ipc://{Path(default_socket_dir()) / 'api.sock'}"


def discover_socket_urls() -> list:
    """扫描本机 KiCad 的所有 API socket。

    KiCad 8+ 中 kicad / eeschema / pcbnew 是独立进程，各自监听一个 socket:
      - /tmp/kicad/api.sock         (第一个进程，通常是 kicad 项目管理器)
      - /tmp/kicad/api-<pid>.sock   (后续进程: eeschema、pcbnew 等)
    返回排序后的 URL 列表（api-<pid>.sock 按 pid 升序）。
    """
    sock_dir = Path(default_socket_dir())
    if not sock_dir.is_dir():
        return [default_socket_url()]
    urls = []
    for p in sorted(sock_dir.glob("*.sock")):
        urls.append(f"ipc://{p}")
    return urls or [default_socket_url()]


# 方便引用的文档类型
DOCTYPE_SCHEMATIC = base_types_pb2.DOCTYPE_SCHEMATIC
DOCTYPE_PCB = base_types_pb2.DOCTYPE_PCB
DOCTYPE_SYMBOL = base_types_pb2.DOCTYPE_SYMBOL
DOCTYPE_FOOTPRINT = base_types_pb2.DOCTYPE_FOOTPRINT
DOCTYPE_PROJECT = base_types_pb2.DOCTYPE_PROJECT

DOC_TYPE_NAMES = {
    DOCTYPE_SCHEMATIC: "schematic",
    DOCTYPE_PCB: "pcb",
    DOCTYPE_SYMBOL: "symbol",
    DOCTYPE_FOOTPRINT: "footprint",
    DOCTYPE_PROJECT: "project",
}


class KiCadError(RuntimeError):
    """KiCad 返回非 AS_OK 状态或网络错误。"""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class KiCadNotRunningError(KiCadError):
    """连接不上 KiCad API Server（KiCad 未启动或未启用 API）。"""


class KiCadClient:
    """KiCad API 客户端封装。

    用法::

        with KiCadClient() as kc:
            kc.ping()
            kc.get_version()
    """

    def __init__(self, socket_url: Optional[str] = None,
                 client_name: str = "kicad-mcp",
                 recv_timeout_ms: int = 5000):
        self.socket_url = socket_url or default_socket_url()
        self.client_name = client_name
        self.recv_timeout_ms = recv_timeout_ms
        self._sock: Optional[pynng.Req0] = None

    # ---------------- 生命周期 ----------------

    def connect(self) -> "KiCadClient":
        if self._sock is not None:
            return self
        sock = pynng.Req0()
        try:
            sock.dial(self.socket_url, block=True)
            # 避免 KiCad 主线程忙碌时永久阻塞
            sock.recv_timeout = self.recv_timeout_ms
        except Exception as exc:
            sock.close()
            raise KiCadNotRunningError(
                -1,
                f"无法连接 KiCad API Server ({self.socket_url})。"
                f"请确认 KiCad 已启动且偏好设置里启用了 API Server。原因: {exc}",
            ) from exc
        self._sock = sock
        return self

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def __enter__(self) -> "KiCadClient":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------- 底层请求 ----------------

    def _call(self, msg) -> ApiResponse:
        """发送一条请求，返回已校验状态的 ApiResponse。"""
        if self._sock is None:
            raise KiCadError(-1, "客户端未连接，请先调用 connect()")

        request = ApiRequest()
        request.header.client_name = self.client_name
        # kicad_token 留空表示不做实例校验
        request.message.Pack(msg, type_url_prefix="type.googleapis.com")

        try:
            self._sock.send(bytes(request.SerializeToString()))
            raw = self._sock.recv()
        except Exception as exc:
            raise KiCadError(-1, f"与 KiCad 通信失败: {exc}") from exc

        response = ApiResponse()
        response.ParseFromString(bytes(raw))

        status = response.status.status
        if status != ApiStatusCode.AS_OK:
            err = response.status.error_message or f"KiCad 返回状态码 {status}"
            raise KiCadError(int(status), err)
        return response

    # ---------------- 通用命令 ----------------

    def ping(self) -> None:
        """检查与 KiCad 的连接是否正常。"""
        self._call(base_commands_pb2.Ping())

    def get_version(self) -> str:
        """返回 KiCad 版本字符串，如 '10.0.5'。"""
        resp = self._call(base_commands_pb2.GetVersion())
        out = base_commands_pb2.GetVersionResponse()
        resp.message.Unpack(out)
        v = out.version
        if v.full_version:
            return v.full_version
        return f"{v.major}.{v.minor}.{v.patch}"

    def get_open_documents(self, doc_type: int) -> list:
        """返回当前打开的指定类型文档的 DocumentSpecifier 列表。

        doc_type 传 DOCTYPE_SCHEMATIC / DOCTYPE_PCB 等。
        """
        req = editor_commands_pb2.GetOpenDocuments()
        req.type = int(doc_type)
        resp = self._call(req)
        out = editor_commands_pb2.GetOpenDocumentsResponse()
        resp.message.Unpack(out)
        return list(out.documents)

    def save_document(self, doc: base_types_pb2.DocumentSpecifier) -> None:
        """保存指定文档。"""
        req = editor_commands_pb2.SaveDocument()
        req.document.CopyFrom(doc)
        self._call(req)

    def close_document(self, doc: base_types_pb2.DocumentSpecifier) -> None:
        """Close a saved document after the API response is sent."""
        req = editor_commands_pb2.CloseDocument()
        req.document.CopyFrom(doc)
        self._call(req)

    def get_schematic_state(
        self, doc: base_types_pb2.DocumentSpecifier
    ) -> "editor_commands_pb2.GetSchematicStateResponse":
        """Return unsaved-change and load-repair state for a schematic."""
        req = editor_commands_pb2.GetSchematicState()
        req.document.CopyFrom(doc)
        resp = self._call(req)
        out = editor_commands_pb2.GetSchematicStateResponse()
        resp.message.Unpack(out)
        return out

    def simulate(self, doc: base_types_pb2.DocumentSpecifier,
                 signal: str = "",
                 signals: list[str] | None = None,
                 ) -> "editor_commands_pb2.SimulateResponse":
        """在 KiCad 内置仿真 GUI 中运行当前原理图的 SPICE 仿真。

        需要原理图包含仿真指令（如 ".tran ..."）。返回响应消息。

        Args:
            signal: 单个要显示的信号（如 "v(/OUT)"）。
            signals: 要在波形图中自动显示的信号列表（如 ["v(/OUT)","v(/VIN)"]），
                仿真前作为占位 trace 添加，仿真完成后自动填充显示。
        """
        req = editor_commands_pb2.Simulate()
        req.document.CopyFrom(doc)
        if signal:
            req.signal = signal
        if signals:
            for s in signals:
                req.signals.append(s)
        resp = self._call(req)
        out = editor_commands_pb2.SimulateResponse()
        resp.message.Unpack(out)
        return out

    def reload_libraries(self,
                         doc: base_types_pb2.DocumentSpecifier
                         ) -> "editor_commands_pb2.ReloadLibrariesResponse":
        """重新加载符号库表（无需重启 eeschema）。

        用于 kicad_sch_create_custom_symbol 新增符号后，让 eeschema 立即可用。
        """
        req = editor_commands_pb2.ReloadLibraries()
        req.document.CopyFrom(doc)
        resp = self._call(req)
        out = editor_commands_pb2.ReloadLibrariesResponse()
        resp.message.Unpack(out)
        return out

    def get_title_block(self,
                        doc: base_types_pb2.DocumentSpecifier
                        ) -> "base_types_pb2.TitleBlockInfo":
        """读取文档图纸信息（title/date/revision/company/comments）。"""
        req = editor_commands_pb2.GetTitleBlockInfo()
        req.document.CopyFrom(doc)
        resp = self._call(req)
        out = base_types_pb2.TitleBlockInfo()
        resp.message.Unpack(out)
        return out

    def set_title_block(self,
                        doc: base_types_pb2.DocumentSpecifier,
                        info: "base_types_pb2.TitleBlockInfo") -> None:
        """写入文档图纸信息（title/date/revision/company/comments）。"""
        req = editor_commands_pb2.SetTitleBlockInfo()
        req.document.CopyFrom(doc)
        req.title_block.CopyFrom(info)
        self._call(req)

    def create_items(
        self,
        header: base_types_pb2.ItemHeader,
        item_messages: list,
    ) -> "editor_commands_pb2.CreateItemsResponse":
        """在文档上创建一组元素。

        item_messages 是任意 protobuf 消息（如 kiapi.schematic.types.Text、
        kiapi.board.types.Track 等），会被 Pack 成 google.protobuf.Any 发送。
        """
        req = editor_commands_pb2.CreateItems()
        req.header.CopyFrom(header)
        for msg in item_messages:
            any_item = req.items.add()
            any_item.Pack(msg, type_url_prefix="type.googleapis.com")
        resp = self._call(req)
        out = editor_commands_pb2.CreateItemsResponse()
        resp.message.Unpack(out)
        return out

    def get_items(
        self,
        header: base_types_pb2.ItemHeader,
        types: list,
    ) -> "editor_commands_pb2.GetItemsResponse":
        """按类型查询文档中的元素。

        types 是 kiapi.common.types.KiCadObjectType 枚举值列表
        （如 KOT_SCH_TEXT / KOT_SCH_SYMBOL / KOT_SCH_LINE）。
        """
        req = editor_commands_pb2.GetItems()
        req.header.CopyFrom(header)
        for t in types:
            req.types.append(int(t))
        resp = self._call(req)
        out = editor_commands_pb2.GetItemsResponse()
        resp.message.Unpack(out)
        return out

    def update_items(
        self,
        header: base_types_pb2.ItemHeader,
        item_messages: list,
    ) -> "editor_commands_pb2.UpdateItemsResponse":
        """更新文档中的一组元素。

        item_messages 是携带目标 KIID 的完整 protobuf 消息
        （通过 GetItems 获取后修改），会被 Pack 成 Any 发送。
        """
        req = editor_commands_pb2.UpdateItems()
        req.header.CopyFrom(header)
        for msg in item_messages:
            any_item = req.items.add()
            any_item.Pack(msg, type_url_prefix="type.googleapis.com")
        resp = self._call(req)
        out = editor_commands_pb2.UpdateItemsResponse()
        resp.message.Unpack(out)
        return out

    def delete_items(
        self,
        header: base_types_pb2.ItemHeader,
        item_ids: list,
    ) -> "editor_commands_pb2.DeleteItemsResponse":
        """按 KIID 删除文档中的一组元素。

        item_ids 是 str 形式的 KIID（如 "3a2b..."）。
        """
        req = editor_commands_pb2.DeleteItems()
        req.header.CopyFrom(header)
        for iid in item_ids:
            # NOTE: chained add().set_value() fails on protobuf upb backend
            kid = req.item_ids.add()
            kid.value = iid
        resp = self._call(req)
        out = editor_commands_pb2.DeleteItemsResponse()
        resp.message.Unpack(out)
        return out


# ---------------- 辅助构造 ----------------

def find_document_socket(doc_type: int):
    """自动发现能处理指定文档类型的 KiCad 进程 socket。

    返回 (socket_url, [打开文档列表])；找不到返回 (None, [])。
    内部会逐一连接所有发现的 socket，能返回该类型打开文档的那个即命中。
    """
    for url in discover_socket_urls():
        try:
            with KiCadClient(url, client_name="kicad-mcp") as kc:
                docs = kc.get_open_documents(doc_type)
                if docs:
                    return url, docs
        except Exception:
            continue
    return None, []


def make_document_specifier(
    doc_type: int,
    board_filename: Optional[str] = None,
    project_name: Optional[str] = None,
    project_path: Optional[str] = None,
    sheet_path: Optional[str] = None,
    library_nickname: Optional[str] = None,
    entry_name: Optional[str] = None,
) -> base_types_pb2.DocumentSpecifier:
    """构造 DocumentSpecifier。

    - 原理图/PCB 通常只需 doc_type (+ project 用于定位)。
    - PCB 可按文件名定位: board_filename="board.kicad_pcb"。
    - 符号/封装库条目: library_nickname + entry_name。
    """
    spec = base_types_pb2.DocumentSpecifier()
    spec.type = int(doc_type)

    if doc_type in (DOCTYPE_SCHEMATIC, DOCTYPE_PCB, DOCTYPE_PROJECT):
        if project_name is not None or project_path is not None:
            spec.project.name = project_name or ""
            spec.project.path = project_path or ""

    if board_filename is not None:
        spec.board_filename = board_filename

    if sheet_path is not None:
        spec.sheet_path.path_human_readable = sheet_path

    if library_nickname is not None or entry_name is not None:
        spec.lib_id.library_nickname = library_nickname or ""
        spec.lib_id.entry_name = entry_name or ""

    return spec
