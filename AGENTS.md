# Repository agent instructions

Use [docs/AI_SETUP.md](docs/AI_SETUP.md) as the canonical environment, build, run, and test procedure.

## Required workflow

- Windows bootstrap: `powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1`
- Debian/Ubuntu bootstrap: `./scripts/bootstrap.sh --install-system-deps`
- Repeated setup is idempotent; omit the dependency-install switch after the first run.
- Use only KiCad from `build/install/<build-name>/bin`. Do not fall back to a system KiCad unless the user explicitly sets `KICAD_ALLOW_PATH=1`.
- Open the exact target `.kicad_sch` in repository Eeschema before API integration tests.
- Run the portable MCP test suite listed in `docs/AI_SETUP.md`; `test_ngcirc.py` is Linux-only.
- Finish schematic changes with `kicad-mcp-quality <schematic>`.
- Read dirty schematic files before editing and preserve unrelated user changes.

## Drawing primitives

Before adding a schematic primitive, consult the prioritized table in `docs/AI_SETUP.md`. Native primitives require protobuf, C++ serialization/handlers, Python CRUD wrappers, and save/reload coverage. Two clean reload rounds are part of the definition of done.
