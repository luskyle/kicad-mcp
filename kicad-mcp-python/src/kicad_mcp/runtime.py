"""Cross-platform discovery of the KiCad runtime used by MCP tools."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CMakeLists.txt").is_file() and (parent / "kicad-mcp-python").is_dir():
            return parent
    return Path(__file__).resolve().parents[3]


def _version_key(path: Path) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in path.name.split("."))
    except ValueError:
        return ()


@dataclass(frozen=True)
class KiCadRuntime:
    """Resolved KiCad executable, stock data and user configuration paths."""

    cli: Path
    stock_data_home: Path
    config_dir: Path
    source: str

    @property
    def symbol_dir(self) -> Path:
        return self.stock_data_home / "symbols"

    @property
    def eeschema(self) -> Path:
        executable = "eeschema.exe" if os.name == "nt" else "eeschema"
        path = self.cli.with_name(executable)
        if not path.is_file():
            raise RuntimeError(f"仓库 Eeschema 不存在: {path}")
        return path

    @property
    def symbol_lib_table(self) -> Path:
        return self.config_dir / "sym-lib-table"

    def cli_env(self, environ: Optional[Mapping[str, str]] = None) -> dict[str, str]:
        env = dict(os.environ if environ is None else environ)
        for name in ("CONDA_PREFIX", "CONDA_DEFAULT_ENV", "PYTHONHOME", "PYTHONPATH"):
            env.pop(name, None)
        env["KICAD_STOCK_DATA_HOME"] = str(self.stock_data_home)
        return env


def _config_dir(environ: Mapping[str, str], platform: str) -> Path:
    explicit = environ.get("KICAD_CONFIG_DIR")
    if explicit:
        return Path(explicit).expanduser()

    if platform == "nt":
        base = Path(environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "kicad"
    else:
        base = Path(environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kicad"

    versions = sorted(
        (path for path in base.iterdir() if path.is_dir() and _version_key(path)),
        key=_version_key,
        reverse=True,
    ) if base.is_dir() else []
    return versions[0] if versions else base / "10.0"


def resolve_kicad_runtime(
    environ: Optional[Mapping[str, str]] = None,
    platform: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> KiCadRuntime:
    """Resolve KiCad using explicit environment, repository install, then PATH."""
    env = dict(os.environ if environ is None else environ)
    platform = os.name if platform is None else platform
    root = _repo_root() if repo_root is None else Path(repo_root)
    executable = "kicad-cli.exe" if platform == "nt" else "kicad-cli"

    explicit_cli = env.get("KICAD_CLI")
    if explicit_cli:
        cli = Path(explicit_cli).expanduser()
        source = "KICAD_CLI"
    else:
        candidates = [
            root / "build" / "install" / "msvc-local-release" / "bin" / executable,
            root / "build" / "msvc-local-release" / "kicad" / "Release" / executable,
            root / "build" / "kicad" / executable,
        ]
        cli = next((path for path in candidates if path.is_file()), None)
        source = "repository"
        if cli is None and env.get("KICAD_ALLOW_PATH") == "1":
            found = shutil.which(executable, path=env.get("PATH"))
            if not found:
                raise RuntimeError(
                    "PATH 中找不到 kicad-cli"
                )
            cli = Path(found)
            source = "PATH"
        elif cli is None:
            raise RuntimeError(
                "找不到仓库构建的 kicad-cli；请先构建当前 KiCad 仓库，"
                "或显式设置 KICAD_CLI"
            )

    if not cli.is_file():
        raise RuntimeError(f"kicad-cli 不存在: {cli}")

    explicit_stock = env.get("KICAD_STOCK_DATA_HOME")
    if explicit_stock:
        stock = Path(explicit_stock).expanduser()
    else:
        repo_stock = root / "build" / "install" / "msvc-local-release" / "share" / "kicad"
        adjacent_stock = cli.parent.parent / "share" / "kicad"
        stock = next(
            (path for path in (repo_stock, adjacent_stock) if path.is_dir()),
            None,
        )
        if stock is None:
            raise RuntimeError(
                "找不到 KiCad stock data；请设置 KICAD_STOCK_DATA_HOME"
            )

    if not stock.is_dir():
        raise RuntimeError(f"KiCad stock data 不存在: {stock}")

    return KiCadRuntime(
        cli=cli.resolve(),
        stock_data_home=stock.resolve(),
        config_dir=_config_dir(env, platform).resolve(),
        source=source,
    )


def find_kicad_cli() -> str:
    return str(resolve_kicad_runtime().cli)


def kicad_cli_env() -> dict[str, str]:
    return resolve_kicad_runtime().cli_env()