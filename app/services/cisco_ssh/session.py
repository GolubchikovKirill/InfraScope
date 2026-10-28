"""One interactive SSH session to a Cisco IOS device (paramiko underneath)."""

from __future__ import annotations

import logging
import re
import socket
import time
from collections.abc import Callable
from contextlib import suppress

import paramiko

from app.observability.metrics import (
    observe_duration,
    ssh_connect_duration_seconds,
    ssh_operations_total,
    ssh_session_reuse_total,
)

logger = logging.getLogger("app.services.cisco_ssh")

SSH_TIMEOUT = 15
CMD_TIMEOUT = 30
RECV_CHUNK = 65535
RECV_WAIT = 0.5


def _classify_ssh_error(exc: Exception) -> str:
    """Classify a connect failure so callers can tell "wrong password" apart
    from "switch unreachable" - both surface as a bare Exception from
    paramiko/socket, and every path here used to collapse them into the same
    "auth failed" log line. That mislabeling cost three days of misdiagnosis
    once: a Docker network misconfiguration blackholed all switch traffic,
    but the log said the password was wrong on every single switch.

    Order matters: AuthenticationException must be checked before the
    broader SSHException it subclasses, and OSError before Exception.
    """
    if isinstance(exc, paramiko.AuthenticationException):
        return "auth_rejected"
    if isinstance(exc, socket.gaierror):
        return "dns_failure"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(exc, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(exc, OSError):
        # Covers "No route to host", "Network is unreachable", and similar -
        # failures that never reach the SSH protocol at all.
        return "network_unreachable"
    if isinstance(exc, paramiko.SSHException):
        return "protocol_error"
    return "other"


# Which auth method actually worked, per (ip, port, username). A switch answers
# the auth-method probe identically every time, so probing on every connect was
# a whole extra TCP+SSH handshake spent learning something already known.
# Entries are dropped the moment the remembered method stops working, so a
# credential or config change re-probes on the next attempt.
_AUTH_METHOD_CACHE: dict[tuple[str, int, str], str] = {}


class CiscoSSH:
    """Manages an SSH session to a Cisco IOS device."""

    def __init__(self, ip: str, username: str, password: str, enable_password: str = "", port: int = 22):
        self.ip = ip
        self.username = username
        self.password = password
        self.enable_password = enable_password or password
        self.port = port
        self.client: paramiko.SSHClient | None = None
        self.shell: paramiko.Channel | None = None
        # Classification of the most recent connect failure (see
        # _classify_ssh_error). None until a connect attempt has failed.
        self.last_failure_reason: str | None = None

    @property
    def _auth_cache_key(self) -> tuple[str, int, str]:
        return (self.ip, self.port, self.username)

    def _strategy_for(self, name: str) -> Callable[[], bool] | None:
        return {
            "password": self._connect_password,
            "keyboard-interactive": self._connect_keyboard_interactive,
        }.get(name)

    def is_alive(self) -> bool:
        if not self.shell or not self.client:
            return False
        transport = self.client.get_transport()
        return bool(transport and transport.is_active())

    def ensure_connected(self) -> bool:
        """Reopen a shared session that has gone away.

        Cisco drops idle VTY sessions on its own exec-timeout (10 minutes by
        default), and one switch cycle can outlive that: rebooting several APs
        means a 45s pause plus up to 240s of verification for each of them.
        """
        if self.is_alive():
            return True
        self.close()
        return self.connect()

    def connect(self) -> bool:
        # Duration of the whole method, cache hit or not: even the cached-
        # method path still pays for a real TCP+auth handshake, it just skips
        # the extra probe connection that used to precede it.
        with observe_duration(ssh_connect_duration_seconds):
            remembered = _AUTH_METHOD_CACHE.get(self._auth_cache_key)
            if remembered:
                method = self._strategy_for(remembered)
                if method and method():
                    ssh_operations_total.labels(operation="connect", result="success", reason=remembered).inc()
                    return True
                # Credentials or the switch's auth config changed - OR the
                # switch simply isn't reachable right now. Either way, forget
                # what we knew and fall through to a full probe; that probe
                # will fail the same way and give us a real classification
                # below instead of assuming it was a credential problem.
                logger.info(
                    "SSH to %s: cached %s auth no longer works (%s), re-probing",
                    self.ip,
                    remembered,
                    self.last_failure_reason,
                )
                _AUTH_METHOD_CACHE.pop(self._auth_cache_key, None)

            allowed = self._query_auth_methods()
            logger.info("SSH to %s: server allows auth methods: %s", self.ip, allowed)

            strategies: list[tuple[str, Callable[[], bool]]] = []
            if "password" in allowed:
                strategies.append(("password", self._connect_password))
            if "keyboard-interactive" in allowed:
                strategies.append(("keyboard-interactive", self._connect_keyboard_interactive))
            if not strategies:
                strategies = [
                    ("password", self._connect_password),
                    ("keyboard-interactive", self._connect_keyboard_interactive),
                ]

            for name, method in strategies:
                logger.info("SSH to %s: trying %s auth", self.ip, name)
                if method():
                    logger.info("SSH to %s: %s auth succeeded", self.ip, name)
                    _AUTH_METHOD_CACHE[self._auth_cache_key] = name
                    ssh_operations_total.labels(operation="connect", result="success", reason=name).inc()
                    return True
                reason = self.last_failure_reason or "other"
                logger.warning("SSH to %s: %s auth failed (%s)", self.ip, name, reason)
                # reason, not the auth method name: on a genuine auth
                # rejection the two strategies fail for different reasons
                # and both are worth seeing, but on a network-level failure
                # (the common case that used to be mislabeled) both strategies
                # fail identically, and the metric should say so rather than
                # implying two separate credential problems were tried.
                ssh_operations_total.labels(operation="connect", result="error", reason=reason).inc()
            return False

    def _query_auth_methods(self) -> list[str]:
        """Ask the server which auth methods it supports."""
        transport: paramiko.Transport | None = None
        try:
            transport = self._open_transport()
            try:
                transport.auth_none(self.username)
            except paramiko.BadAuthenticationType as e:
                return list(e.allowed_types)
            except paramiko.AuthenticationException:
                return ["password", "keyboard-interactive"]
        except Exception as e:
            logger.debug("SSH auth query to %s failed: %s", self.ip, e)
        finally:
            if transport is not None:
                transport.close()
        return ["password", "keyboard-interactive"]

    def _connect_password(self) -> bool:
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                self.ip,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=SSH_TIMEOUT,
                auth_timeout=SSH_TIMEOUT,
                banner_timeout=SSH_TIMEOUT,
                look_for_keys=False,
                allow_agent=False,
                disabled_algorithms={"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]},
            )
            return self._post_connect()
        except Exception as e:
            self.last_failure_reason = _classify_ssh_error(e)
            logger.debug("SSH password connect to %s: %s (%s)", self.ip, e, self.last_failure_reason)
            self.close()
            return False

    def _connect_keyboard_interactive(self) -> bool:
        """Cisco often uses keyboard-interactive instead of standard password auth."""
        transport: paramiko.Transport | None = None
        try:
            transport = self._open_transport()
            transport.set_keepalive(30)

            password = self.password

            def _ki_handler(_title, _instructions, prompt_list):
                logger.debug("KI prompts from %s: %s", self.ip, prompt_list)
                return [password] * len(prompt_list)

            transport.auth_interactive(self.username, _ki_handler)

            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client._transport = transport  # type: ignore[attr-defined]  # attach an already-authenticated Transport to a bare SSHClient wrapper; no public API for this
            self.shell = transport.open_session()
            self.shell.get_pty()
            self.shell.invoke_shell()
            self.shell.settimeout(CMD_TIMEOUT)
            self._recv_until_prompt()

            self._enter_enable()
            self._send("terminal length 0")
            self._recv_until_prompt()
            return True
        except Exception as e:
            self.last_failure_reason = _classify_ssh_error(e)
            logger.debug("SSH keyboard-interactive to %s: %s (%s)", self.ip, e, self.last_failure_reason)
            self.close()
            return False
        finally:
            if transport is not None and self.client is None:
                transport.close()

    def _open_transport(self) -> paramiko.Transport:
        """Open SSH transport with explicit socket timeout safeguards."""
        sock = socket.create_connection((self.ip, self.port), timeout=SSH_TIMEOUT)
        transport = paramiko.Transport(sock)
        transport.banner_timeout = SSH_TIMEOUT
        transport.start_client(timeout=SSH_TIMEOUT)
        return transport

    def _post_connect(self) -> bool:
        """Open shell and enter privileged mode after successful transport auth."""
        self.shell = self.client.invoke_shell()  # type: ignore[union-attr]
        self.shell.settimeout(CMD_TIMEOUT)
        self._recv_until_prompt()
        self._enter_enable()
        self._send("terminal length 0")
        self._recv_until_prompt()
        return True

    def _enter_enable(self) -> None:
        self._send("enable")
        output = self._recv_until_prompt()
        if "assword" in output:
            self._send(self.enable_password)
            self._recv_until_prompt()

    def close(self) -> None:
        try:
            if self.shell:
                # Graceful session teardown on Cisco side before channel close.
                with suppress(Exception):
                    self.shell.send(b"exit\n")
                with suppress(Exception):
                    self.shell.close()
            if self.client:
                with suppress(Exception):
                    transport = self.client.get_transport()
                    if transport:
                        transport.close()
                with suppress(Exception):
                    self.client.close()
        except Exception as exc:
            logger.debug("Error while closing SSH session: %s", exc)
        self.shell = None
        self.client = None

    def _send(self, cmd: str) -> None:
        if self.shell:
            self.shell.send((cmd + "\n").encode())

    def _recv_until_prompt(self, timeout: float = CMD_TIMEOUT) -> str:
        if not self.shell:
            return ""
        output = ""
        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            time.sleep(RECV_WAIT)
            if self.shell.recv_ready():
                chunk = self.shell.recv(RECV_CHUNK).decode("utf-8", errors="replace")
                output += chunk
                if re.search(r"[#>]\s*$", output):
                    break
            elif output and re.search(r"[#>]\s*$", output):
                break
        return output

    def execute(self, cmd: str) -> str:
        self._send(cmd)
        return self._recv_until_prompt()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()


def _session_for(
    session: CiscoSSH | None,
    ip: str,
    username: str,
    password: str,
    enable_password: str,
    port: int,
) -> tuple[CiscoSSH | None, bool]:
    """Resolve the session an operation should run on.

    Returns (session, owned). `owned` is True when this call opened the
    connection and is therefore responsible for closing it; a session handed
    in by the caller is left open so the next operation in the same cycle can
    reuse it instead of paying for another handshake. Returns (None, ...) if
    no usable connection could be established.

    Every call classifies itself into ssh_session_reuse_total - this is the
    metric that shows the reuse win actually holding cycle over cycle, rather
    than being something only visible by re-reading raw connection logs.
    """
    if session is not None:
        was_alive = session.is_alive()
        if not session.ensure_connected():
            ssh_session_reuse_total.labels(outcome="connect_failed").inc()
            return None, False
        ssh_session_reuse_total.labels(outcome="reused" if was_alive else "new_connection").inc()
        return session, False

    ssh = CiscoSSH(ip, username, password, enable_password, port)
    if ssh.connect():
        ssh_session_reuse_total.labels(outcome="new_connection").inc()
        return ssh, True
    ssh_session_reuse_total.labels(outcome="connect_failed").inc()
    return None, True
