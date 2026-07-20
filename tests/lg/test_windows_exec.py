"""Tests for Windows argv resolution and classify helpers."""

from __future__ import annotations

import json
import os
import platform
import sys

import pytest

from log_guard.lg.classify import (
    Track,
    is_python_inline,
    looks_like_machine_json,
    resolve_track,
    split_command_string,
)
from log_guard.lg.runner import run_exec
from log_guard.lg.track_config import (
    daemon_commands,
    lossless_commands,
    passthrough_prefixes,
    rtk_fast_commands,
)

PY = sys.executable


def _resolve(cmd: str, *, shell: bool = False) -> Track:
    return resolve_track(
        cmd,
        shell_mode=shell,
        passthrough_prefixes=passthrough_prefixes(),
        lossless_commands=lossless_commands(),
        rtk_fast_commands=rtk_fast_commands(),
        daemon_commands=daemon_commands(),
    )


def test_python_c_routes_passthrough():
    assert is_python_inline("python -c \"print(1)\"")
    assert _resolve("python -c \"import json; print({})\"") == Track.PASSTHROUGH


def test_looks_like_machine_json():
    assert looks_like_machine_json('{"a": 1}\n')
    assert looks_like_machine_json("[1, 2, 3]")
    assert not looks_like_machine_json("not json\n")


def test_split_python_c_fallback_triple_quotes():
    if platform.system() != "Windows":
        pytest.skip("Windows shlex fallback")
    cmd = "python -c \"script = r'''line1\\nline2''' ; print('ok')\""
    argv = split_command_string(cmd)
    assert argv[0] == "python"
    assert argv[1] == "-c"
    assert "script = r'''line1" in argv[2]


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows PowerShell cmdlets")
def test_powershell_get_childitem_exec():
    result = run_exec(["Get-ChildItem", "-Path", "."])
    assert result.exit_code == 0
    assert "command not found" not in result.stderr.lower()


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows PowerShell cmdlets")
def test_powershell_new_item_exec(tmp_path):
    target = tmp_path / "lg-test-dir"
    result = run_exec(["New-Item", "-ItemType", "Directory", "-Path", str(target), "-Force"])
    assert result.exit_code == 0
    assert target.is_dir()


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows ls via Git usr/bin")
def test_ls_resolves_git_bash_when_not_on_path():
    if os.environ.get("PATH", "").lower().find("ls.exe") >= 0:
        pytest.skip("ls already on PATH")
    result = run_exec(["ls", "-la", "."])
    assert "Failed to resolve" not in result.stdout
    assert "program not found" not in result.stderr.lower()
    assert result.exit_code in (0, 1)


def test_python_c_json_preserved_via_cli(tmp_path, monkeypatch):
    from tests.lg.test_cli_integration import _lg

    monkeypatch.setenv("LOGGUARD_HOME", str(tmp_path))
    payload = json.dumps({"metrics": [1, 2, 3]})
    proc = _lg("run", "--dry-run", PY, "-c", f"import json; print({payload!r})")
    assert proc.returncode == 0
    assert payload in proc.stdout
    assert "SyntaxError" not in proc.stdout
