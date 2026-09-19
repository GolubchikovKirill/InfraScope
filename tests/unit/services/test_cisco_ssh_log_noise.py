from __future__ import annotations

import logging
import threading

import pytest

import app.services.cisco_ssh  # noqa: F401  (installs the filter on import)

TRANSPORT = "paramiko.transport"


def _emit_in_thread(*messages: str, level: int = logging.ERROR) -> None:
    def _run() -> None:
        log = logging.getLogger(TRANSPORT)
        for message in messages:
            log.log(level, message)

    t = threading.Thread(target=_run)
    t.start()
    t.join()


@pytest.fixture
def records(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG, logger=TRANSPORT)
    return caplog


def test_incompatible_peer_traceback_is_muted(records):
    _emit_in_thread(
        "Exception (client): Incompatible ssh peer (no acceptable kex algorithm)",
        "Traceback (most recent call last):",
        '  File "paramiko/transport.py", line 2080, in run',
        "paramiko.ssh_exception.IncompatiblePeer: Incompatible ssh peer (no acceptable kex algorithm)",
    )

    assert [r for r in records.records if r.name == TRANSPORT] == []


def test_other_paramiko_errors_still_get_logged(records):
    _emit_in_thread("Exception (client): Authentication failed.", "Traceback (most recent call last):")

    messages = [r.getMessage() for r in records.records if r.name == TRANSPORT]
    assert messages == ["Exception (client): Authentication failed.", "Traceback (most recent call last):"]


def test_muting_is_per_thread_so_a_later_failure_is_not_swallowed(records):
    _emit_in_thread("Exception (client): Incompatible ssh peer (no acceptable kex algorithm)", "Traceback ...")
    _emit_in_thread("Socket exception: Connection reset by peer (104)")

    messages = [r.getMessage() for r in records.records if r.name == TRANSPORT]
    assert messages == ["Socket exception: Connection reset by peer (104)"]


def test_debug_and_info_records_are_never_filtered(records):
    _emit_in_thread(
        "Exception (client): Incompatible ssh peer (no acceptable kex algorithm)",
        level=logging.ERROR,
    )
    _emit_in_thread("EOF in transport thread", level=logging.DEBUG)

    messages = [r.getMessage() for r in records.records if r.name == TRANSPORT]
    assert messages == ["EOF in transport thread"]


def test_filter_is_installed_exactly_once_even_after_a_reload():
    import importlib

    import app.services.cisco_ssh as mod

    importlib.reload(mod)

    installed = [f for f in logging.getLogger(TRANSPORT).filters if type(f).__name__ == "_QuietIncompatiblePeer"]
    assert len(installed) == 1
