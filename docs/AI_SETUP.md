# AI environment bootstrap

This is the canonical setup procedure for AI agents and humans working on this repository. Do not use a system KiCad unless `KICAD_ALLOW_PATH=1` is explicitly requested. The MCP runtime must resolve to this repository's install tree.

## One-command setup

Run from the repository root.

### Windows 10/11

Prerequisites: PowerShell 5.1+, Git, CMake, Ninja, Python 3.10+, and Visual Studio 2022 Build Tools with **Desktop development with C++**.

```powershell
Set-ExecutionPolicy -Scope Process RemoteSigned
.\scripts\bootstrap.ps1
```

On a machine with winget but without prerequisites:

```powershell
.\scripts\bootstrap.ps1 -InstallSystemDependencies
# Reopen PowerShell if winget changed PATH, then rerun without the switch.
```

The script finds or clones vcpkg under `%USERPROFILE%\vcpkg`, imports the MSVC x64 environment, configures and installs a complete Ninja Release build, creates `kicad-mcp-python\.venv`, runs core tests, and writes MCP client configuration.

Useful development modes:

```powershell
# Python/MCP setup and tests against an existing install tree
.\scripts\bootstrap.ps1 -SkipKiCadBuild

# Configure/build only while iterating
.\scripts\bootstrap.ps1 -SkipTests
```

### Debian/Ubuntu Linux

```bash
chmod +x scripts/bootstrap.sh install-deps.sh
./scripts/bootstrap.sh --install-system-deps
```

After system packages are installed, repeated runs are unprivileged and idempotent:

```bash
./scripts/bootstrap.sh
```

Other Linux distributions must install the dependencies equivalent to `install-deps.sh`, then run `./scripts/bootstrap.sh` without `--install-system-deps`.

## Outputs

| Item | Windows | Linux |
| --- | --- | --- |
| Build tree | `build/msvc-local-release` | `build/linux-local-release` |
| Install tree | `build/install/msvc-local-release` | `build/install/linux-local-release` |
| MCP environment | `kicad-mcp-python/.venv` | `kicad-mcp-python/.venv` |
| VS Code config fragment | `build/mcp-config/vscode-mcp.json` | same |
| Claude config fragment | `build/mcp-config/claude-mcp.json` | same |

The generated client fragments set `KICAD_CLI` and `KICAD_STOCK_DATA_HOME`, preventing accidental use of another KiCad installation.

## Start and verify

Open a project with the repository Eeschema:

```powershell
# Windows
.\build\install\msvc-local-release\bin\eeschema.exe .\demos\keyboard-89\keyboard-89.kicad_sch
```

```bash
# Linux
./build/install/linux-local-release/bin/eeschema ./demos/keyboard-89/keyboard-89.kicad_sch
```

Then verify the API and run the full schematic quality pipeline:

```powershell
cd kicad-mcp-python
.\.venv\Scripts\python.exe -m kicad_mcp.check
.\.venv\Scripts\kicad-mcp-quality.exe ..\demos\keyboard-89\keyboard-89.kicad_sch
```

```bash
cd kicad-mcp-python
./.venv/bin/python -m kicad_mcp.check
./.venv/bin/kicad-mcp-quality ../demos/keyboard-89/keyboard-89.kicad_sch
```

The quality command runs schema, topology, ERC, geometry, reload, visual, and Golden gates. A valid production run must report all seven gates passed.

## Core test command

The bootstrap deliberately runs the portable MCP suite instead of unrestricted `pytest`: `tests/test_ngcirc.py` directly loads `libngspice.so.0` and is Linux-only.

```text
test_project.py test_runtime.py test_reload_gate.py test_mcp_stdio.py
test_geometry.py test_constraint_layout.py test_label_placement.py
test_pathfinding.py test_svg_metrics.py test_draw_report.py
```

Run KiCad C++ tests separately only when changing shared KiCad internals; MCP Python-only work does not require rebuilding all QA targets.

## Recommended new schematic primitives

The current API already supports text, wire/bus/notes lines, symbols, labels, graphical shapes, no-connects, images, bus entries, transform, layout, routing, ERC, reload, and rendering. The next primitives should be added in this order:

| Priority | Primitive | Why it matters | Required API work |
| --- | --- | --- | --- |
| P0 | `kicad_sch_add_sheet` / `add_sheet_pin` | Enables generated multi-page and reusable hierarchy instead of hand-editing `.kicad_sch` | Add `Sheet` and `SheetPin` protobuf serialization and hierarchy instance handling |
| P0 | `kicad_sch_add_junction` | Gives explicit control over three-way same-net joins and supports route repair | Expose existing `Junction` message as a public tool |
| P0 | `kicad_sch_update_item` / `delete_items` | Enables transactional repair and batch rollback for every supported object | Generalize existing per-text update/delete wrappers |
| P1 | `kicad_sch_add_text_box` | Needed for functional blocks, design notes, constraints, and review annotations | Add `SCH_TEXTBOX` protobuf mapping |
| P1 | `kicad_sch_add_netclass_directive` | Carries impedance/current/clearance intent from schematic to PCB | Add directive/netclass field serialization |
| P1 | `kicad_sch_add_power_port` | Creates a power symbol, label, optional PWR_FLAG, and ERC intent atomically | High-level Python primitive using existing symbol/label/wire APIs |
| P1 | `kicad_sch_add_harness` | Provides typed multi-signal connectivity beyond simple buses | Requires harness wire/entry/label protobuf types |
| P2 | `kicad_sch_add_table` | Supports connector maps, strap tables, and design metadata | Add schematic table/cell serialization |
| P2 | `kicad_sch_add_rule_area` | Marks keepouts and controlled drawing regions for the constraint solver | Python geometry primitive first; native object if KiCad supports it |
| P2 | advanced shape style | Adds dash style, line color, fill color, and opacity to polyline/bezier/arc | Extend `Shape` styling fields |

Implementation rule: add the protobuf type and C++ serializer first, then Python create/get/update/delete wrappers, then save/reload and SVG tests. A primitive is not complete until it survives two reload rounds without automatic repair.

## AI execution contract

1. Read this file and `kicad-mcp-python/docs/drawing-improvement-plan.md` before changing build or drawing code.
2. Run the platform bootstrap. Do not invent a new install path.
3. Confirm `kicad-cli` and `eeschema` come from `build/install/<build-name>/bin`.
4. Keep project files complete: `.kicad_pro`, `sym-lib-table`, and `fp-lib-table` must accompany generated schematics.
5. For Python changes, run the portable core suite. For native API changes, rebuild `eeschema` and `kicad-cli` and rerun reload tests.
6. Open the exact target schematic with repository Eeschema before API integration tests.
7. Finish with `kicad-mcp-quality`; retain its JSON, SVG, and Golden artifacts when they are intentional fixtures.
8. Never overwrite unrelated dirty-worktree changes or generated schematic edits without reading them first.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `cmake --preset` says preset missing | Use the bootstrap scripts; `CMakeUserPresets.json` is machine-local and must not be assumed |
| CMake cannot find a compiler on Windows | Install the C++ Build Tools workload; the script imports `VsDevCmd.bat` automatically |
| `kicad-cli` resolves to Program Files or `/usr/bin` | Use generated MCP config; unset `KICAD_ALLOW_PATH` |
| MCP reports no schematic process | Start repository `eeschema` with the exact `.kicad_sch` path |
| Automatic repair popup | Save once, inspect `GetSchematicState.load_had_repairs`, then fix hierarchy UUID/instance metadata and rerun reload gate |
| `libngspice.so.0` missing on Windows | Do not run Linux-only `test_ngcirc.py`; use the portable suite |
| Fontconfig warning on Windows | Non-blocking if SVG export succeeds; `KICAD_STOCK_DATA_HOME` must still point at the repository install tree |
