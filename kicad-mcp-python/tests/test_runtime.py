from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.runtime import resolve_kicad_runtime


def _runtime_tree(tmp_path: Path, windows: bool = True) -> tuple[Path, Path, Path]:
    executable = "kicad-cli.exe" if windows else "kicad-cli"
    cli = tmp_path / "build" / "install" / "msvc-local-release" / "bin" / executable
    stock = tmp_path / "build" / "install" / "msvc-local-release" / "share" / "kicad"
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"")
    stock.mkdir(parents=True)
    return tmp_path, cli, stock


def test_runtime_prefers_explicit_environment(tmp_path: Path) -> None:
    cli = tmp_path / "custom" / "kicad-cli.exe"
    stock = tmp_path / "custom" / "share" / "kicad"
    config = tmp_path / "config"
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"")
    stock.mkdir(parents=True)

    runtime = resolve_kicad_runtime(
        {
            "KICAD_CLI": str(cli),
            "KICAD_STOCK_DATA_HOME": str(stock),
            "KICAD_CONFIG_DIR": str(config),
        },
        platform="nt",
        repo_root=tmp_path,
    )

    assert runtime.cli == cli.resolve()
    assert runtime.stock_data_home == stock.resolve()
    assert runtime.config_dir == config.resolve()
    assert runtime.source == "KICAD_CLI"


def test_runtime_discovers_repository_install(tmp_path: Path) -> None:
    root, cli, stock = _runtime_tree(tmp_path)
    appdata = tmp_path / "AppData"
    (appdata / "kicad" / "9.0").mkdir(parents=True)
    (appdata / "kicad" / "10.0").mkdir(parents=True)

    runtime = resolve_kicad_runtime(
        {"APPDATA": str(appdata), "PATH": ""},
        platform="nt",
        repo_root=root,
    )

    assert runtime.cli == cli.resolve()
    assert runtime.stock_data_home == stock.resolve()
    assert runtime.config_dir == (appdata / "kicad" / "10.0").resolve()
    assert runtime.source == "repository"


def test_runtime_cli_environment_preserves_platform_path(tmp_path: Path) -> None:
    root, _, _ = _runtime_tree(tmp_path)
    runtime = resolve_kicad_runtime(
        {"APPDATA": str(tmp_path / "config"), "PATH": "windows-path"},
        platform="nt",
        repo_root=root,
    )

    env = runtime.cli_env({"PATH": "windows-path", "PYTHONHOME": "bad"})

    assert env["PATH"] == "windows-path"
    assert "PYTHONHOME" not in env
    assert env["KICAD_STOCK_DATA_HOME"] == str(runtime.stock_data_home)


def test_runtime_uses_latest_linux_xdg_config(tmp_path: Path) -> None:
    root, cli, stock = _runtime_tree(tmp_path, windows=False)
    xdg = tmp_path / "xdg"
    (xdg / "kicad" / "9.0").mkdir(parents=True)
    (xdg / "kicad" / "10.0").mkdir(parents=True)

    runtime = resolve_kicad_runtime(
        {"XDG_CONFIG_HOME": str(xdg), "PATH": ""},
        platform="posix",
        repo_root=root,
    )

    assert runtime.cli == cli.resolve()
    assert runtime.stock_data_home == stock.resolve()
    assert runtime.config_dir == (xdg / "kicad" / "10.0").resolve()


def test_runtime_rejects_missing_explicit_cli(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="kicad-cli 不存在"):
        resolve_kicad_runtime(
            {
                "KICAD_CLI": str(tmp_path / "missing.exe"),
                "KICAD_STOCK_DATA_HOME": str(tmp_path),
            },
            platform="nt",
            repo_root=tmp_path,
        )


def test_runtime_does_not_fall_back_to_path_by_default(tmp_path: Path) -> None:
    path_dir = tmp_path / "path-bin"
    path_dir.mkdir()
    (path_dir / "kicad-cli.exe").write_bytes(b"")

    with pytest.raises(RuntimeError, match="仓库构建"):
        resolve_kicad_runtime(
            {"PATH": str(path_dir), "APPDATA": str(tmp_path / "config")},
            platform="nt",
            repo_root=tmp_path / "repo",
        )