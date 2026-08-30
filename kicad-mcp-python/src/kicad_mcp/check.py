"""自检脚本: 验证与本机 KiCad API Server 的连通性。

用法:
    python -m kicad_mcp.check
"""

from __future__ import annotations

from .client import (
    DOC_TYPE_NAMES,
    KiCadClient,
    KiCadNotRunningError,
)


def main() -> int:
    print("=== KiCad MCP 连通性自检 ===")
    print(f"socket: {KiCadClient().socket_url}")

    try:
        with KiCadClient(client_name="kicad-mcp-check") as kc:
            try:
                kc.ping()
                print("[OK] ping 成功")
            except Exception as exc:
                if "no handler available" not in str(exc):
                    raise
                print("[OK] API 已连接（当前编辑器未注册 Ping handler）")

            try:
                print(f"[OK] KiCad 版本: {kc.get_version()}")
            except Exception as exc:
                if "no handler available" not in str(exc):
                    raise
                print("[OK] 当前编辑器未注册版本查询 handler，跳过版本检查")

            for dtype in (1, 3):  # schematic, pcb
                name = DOC_TYPE_NAMES.get(dtype, f"type{dtype}")
                try:
                    docs = kc.get_open_documents(dtype)
                    if docs:
                        print(f"[OK] 打开的 {name} 文档: {len(docs)} 个")
                        for d in docs:
                            print(f"      - {d}")
                    else:
                        print(f"[OK] 当前没有打开的 {name} 文档")
                except Exception as exc:
                    if "no handler available" in str(exc):
                        print(f"[OK] 当前 KiCad 进程不处理 {name} 文档")
                    else:
                        print(f"[!!] 查询 {name} 文档失败: {exc}")
    except KiCadNotRunningError as exc:
        print(f"[FAIL] {exc}")
        print()
        print("提示: 请确认")
        print("  1) KiCad 10.x 已启动（API Server 随 KiCad 一起运行）")
        print("  2) 偏好设置已启用 API: Preferences -> Api -> Enable server")
        return 1
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        return 1

    print("\n=== 自检完成 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
