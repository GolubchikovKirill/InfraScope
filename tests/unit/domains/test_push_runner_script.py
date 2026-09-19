"""Static guards for the Windows push runner (deploy-runner/Run-PushRunner.ps1).

The runner executes on an admin machine with rights over the whole fleet, so what it must
never do is pinned here: reboot anything, leave the machines' passwords on disk, run code
fetched from the server.
"""

from __future__ import annotations

import re
from pathlib import Path

RUNNER = (Path(__file__).resolve().parents[3] / "deploy-runner" / "Run-PushRunner.ps1").read_text(encoding="utf-8")
CODE = "\n".join(line for line in RUNNER.splitlines() if not line.lstrip().startswith("#"))


def test_it_never_reboots_or_updates_anything() -> None:
    assert not re.search(r"Restart-Computer|Stop-Computer|shutdown(\.exe)?\s|-Restart\b|wusa|Install-WindowsUpdate", CODE, re.IGNORECASE)


def test_it_runs_the_push_kit_and_nothing_fetched_from_the_server() -> None:
    assert "Push-RustDesk.ps1" in CODE
    # whatever the server sends is data (a config), never code
    assert not re.search(r"Invoke-Expression|\biex\b|DownloadString|Add-Type|\[scriptblock\]::Create", CODE, re.IGNORECASE)


def test_the_machines_password_file_is_removed_even_when_the_push_fails() -> None:
    finally_block = re.search(r"finally\s*\{[^}]*Remove-Item\s+\$configFile[^}]*\}", CODE, re.DOTALL)
    assert finally_block, "the temp config (it holds a RustDesk password) must be deleted in a finally block"


def test_the_runner_token_is_only_ever_sent_as_a_header_never_stored() -> None:
    assert "X-InfraScope-Runner-Token" in CODE
    assert not re.search(r"Set-Content|Out-File|WriteAllText\([^)]*\$Token", CODE)  # the only file written is the job config
    assert "$Token" not in re.sub(r"'X-InfraScope-Runner-Token'\s*=\s*\$Token|\[string\]\$Token|Mandatory", "", CODE)


def test_it_speaks_tls12_because_windows_powershell_51_defaults_to_older() -> None:
    assert "SecurityProtocolType]::Tls12" in CODE


def test_every_result_of_the_kit_is_mapped_to_one_the_server_accepts() -> None:
    mapping = dict(re.findall(r"'([A-Z-]+)'\s*=\s*'([a-z_]+)'", CODE))
    assert mapping == {"OK": "ok", "WARN": "warn", "FAILED": "failed", "SKIPPED": "skipped", "DRY-RUN": "dry_run"}


def test_it_does_not_shadow_powershells_automatic_variables() -> None:
    assert not re.search(r"\$args\s*=|\$input\s*=|\$matches\s*=|\$host\s*=", CODE, re.IGNORECASE)
