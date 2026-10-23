"""Every module must at least compile; entry points must import. (Catches syntax errors in code the other tests never load, e.g. cli.py.)"""

import py_compile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted(p for p in (ROOT / "sasayaki").rglob("*.py"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_module_compiles(path, tmp_path):
    py_compile.compile(str(path), cfile=str(tmp_path / "x.pyc"), doraise=True)


def test_cli_imports_and_has_sync_command():
    from sasayaki import cli

    assert callable(cli.cmd_sync)
