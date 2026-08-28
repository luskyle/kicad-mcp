"""L4 Golden 回归：重画已验证电路并对比电气结构（netlist 连通性 + 标签）。

用法（需要 eeschema 打开一个空 .kicad_sch）:
    python tests/run_golden.py             # 运行全部回归（重画 + 对比 golden）
    python tests/run_golden.py --gen       # 重新生成 golden 基线（验证过的）
    python tests/run_golden.py rc divider  # 只跑指定项
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SRC = TESTS.parent / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from kicad_mcp.golden import (  # noqa: E402
    compare,
    load_golden,
    make_golden,
    save_golden,
)
from kicad_mcp.tools.circuit import kicad_sch_draw_circuit  # noqa: E402
from kicad_mcp.tools.common import kicad_save_document  # noqa: E402
from kicad_mcp.tools.schematic import _current_sch_path  # noqa: E402
from redraw_kb89 import flash_json, matrix_json, power_json  # noqa: E402
from test_draw_circuit import DIVIDER, RC  # noqa: E402


def _specs() -> dict:
    def _tidy(d: dict) -> dict:
        d = dict(d)
        d.update(clear=True, run_erc=False, render=False)
        return d

    return {
        "rc": _tidy(RC),
        "divider": _tidy(DIVIDER),
        "flash": _tidy(flash_json()),
        "power": _tidy(power_json()),
        "matrix": _tidy(matrix_json()),
    }


def main() -> None:
    gen = "--gen" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    specs = _specs()
    names = args or list(specs)
    sch = _current_sch_path()
    results = []
    for n in names:
        print(f"\n{'='*50}\n=== {n} ===")
        try:
            kicad_sch_draw_circuit(json.dumps(specs[n], ensure_ascii=False))
            kicad_save_document()
        except Exception as exc:
            results.append((False, n, f"重画失败: {exc}"))
            print(f"  ❌ {exc}")
            continue
        if gen:
            g = make_golden(n, sch)
            p = save_golden(n, g)
            results.append((True, n, f"已生成 golden {p}（{len(g['nets'])} 网络）"))
            print(f"  📝 {p}（{len(g['nets'])} 网络 / {len(g['labels'])} 标签）")
        else:
            try:
                golden = load_golden(n)
            except FileNotFoundError as exc:
                results.append((False, n, f"无 golden，先跑 --gen: {exc}"))
                print(f"  ❌ {exc}；请先 python tests/run_golden.py --gen")
                continue
            ok, lines = compare(sch, golden)
            print("\n".join(lines))
            results.append((ok, n, "PASS" if ok else "FAIL"))

    print("\n" + "=" * 50)
    fails = [r for r in results if not r[0]]
    print(f"🏁 Golden 回归汇总: {len(results) - len(fails)}/{len(results)} 通过"
          + ("" if not fails else f"，失败: {[r[1] for r in fails]}"))
    for r in results:
        print(f"  {'✅' if r[0] else '❌'} {r[1]}: {r[2]}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
