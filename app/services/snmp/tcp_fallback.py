from __future__ import annotations

import errno
import selectors
import socket
import time

_TCP_FALLBACK_PORTS = (80, 443, 9100, 631)
_TCP_TIMEOUT = 2.0


def _tcp_port_open(ip: str, port: int, timeout: float = _TCP_TIMEOUT) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def _tcp_any_port_open(ip: str, ports: tuple[int, ...], timeout: float = _TCP_TIMEOUT) -> bool:
    """True as soon as any of `ports` accepts a connection.

    All connects are started at once on non-blocking sockets and waited on with
    one selector, so a silent host costs one timeout instead of one per port:
    the old sequential loop spent 4 x 2 s = 8 s on every offline printer, on a
    worker thread, before the printer could be reported offline.
    """
    try:
        family, _, _, _, sockaddr = socket.getaddrinfo(ip, None, type=socket.SOCK_STREAM)[0]
    except (OSError, IndexError):
        return False
    host = sockaddr[0]
    sel = selectors.DefaultSelector()
    socks: list[socket.socket] = []
    try:
        for port in ports:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.setblocking(False)
            socks.append(sock)
            try:
                rc = sock.connect_ex((host, port))
            except OSError:
                continue  # malformed address and the like - this port is simply not open
            if rc == 0:
                return True
            if rc in (errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY):
                sel.register(sock, selectors.EVENT_WRITE)
        deadline = time.monotonic() + timeout
        while sel.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            for key, _ in sel.select(remaining):
                sock = key.fileobj
                assert isinstance(sock, socket.socket)
                if sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0:
                    return True
                sel.unregister(sock)  # refused / unreachable: wait for the others
        return False
    finally:
        sel.close()
        for sock in socks:
            sock.close()


def _tcp_reachable(ip: str) -> bool:
    """Check if any common printer port is open (HTTP, HTTPS, JetDirect, IPP)."""
    return _tcp_any_port_open(ip, _TCP_FALLBACK_PORTS)
