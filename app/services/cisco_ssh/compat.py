"""paramiko compatibility for old Cisco IOS images.

paramiko 5 dropped the SHA-1 key exchanges and the ssh-rsa host key many of the
store switches still offer. They are put back here - last in preference order,
so a switch that can do better still does - and paramiko's "Incompatible ssh
peer" noise for the ones that cannot be helped is turned down. Importing the
package applies both once per process.
"""

from __future__ import annotations

import hashlib
import logging
import threading

import paramiko
import paramiko.rsakey
from cryptography.hazmat.primitives import hashes
from paramiko.kex_group14 import KexGroup14SHA256


class _KexGroup14SHA1(KexGroup14SHA256):
    """diffie-hellman-group14-sha1 - same 2048-bit MODP group as paramiko's
    own KexGroup14SHA256, just with the legacy SHA-1 exchange hash. Paramiko
    5.0 (pulled in by 63b92b1, "Update vulnerable backend and frontend
    dependencies") dropped every SHA-1 KEX algorithm and the bare "ssh-rsa"
    host-key type entirely - which is all the store fleet's aging Cisco IOS
    switches speak. That silently broke every SSH path in this module; it
    only surfaced as a user-visible outage on /camera-ports because every
    other switch feature has an SNMP fallback (see CiscoSwitchProvider) that
    papers over an SSH failure. This class and _install_legacy_ssh_compat()
    below re-add just enough of the old algorithm set for paramiko to talk to
    those switches again, appended at the *lowest* priority so any switch
    capable of a modern algorithm keeps using it - this is only ever chosen
    when a peer offers nothing else.
    """

    name = "diffie-hellman-group14-sha1"
    hash_algo = hashlib.sha1


class _KexGroup1SHA1(KexGroup14SHA256):
    """diffie-hellman-group1-sha1 - Oakley Group 2 (RFC 2409, 1024-bit MODP) with
    SHA-1. Paramiko dropped kex_group1.py together with the other SHA-1 methods;
    this puts it back for one reason: ~10 Catalyst 2960S/3750E switches on IOS
    12.2(53-55)SE offer nothing else, cannot be upgraded here, and until now
    every SSH feature on them (PoE reboot of access points, camera ports, port
    writes, config snapshots) failed with "no acceptable kex algorithm" while
    SNMP polling quietly kept them "online".

    This is weak cryptography (1024-bit DH is within reach of a well-resourced
    attacker who records the traffic - the Logjam class of attack) and was
    enabled on purpose, as an explicit decision, for the management network
    only. Two things limit the exposure: it is registered at the *lowest*
    priority, so any switch that can do group14/sha256/curve25519 keeps using
    those; and nothing else is loosened.

    P is verified, not remembered: it equals
    2**1024 - 2**960 - 1 + 2**64 * (floor(2**894 * pi) + 129093) (RFC 2409
    section 6.2) and both P and (P-1)/2 are prime -
    tests/unit/services/test_cisco_ssh_legacy_kex_compat.py recomputes that.
    """

    # RFC 2409 section 6.2, "Second Oakley Group"
    P = 0xFFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F24117C4B1FE649286651ECE65381FFFFFFFFFFFFFFFF  # noqa: E501
    G = 2

    name = "diffie-hellman-group1-sha1"
    hash_algo = hashlib.sha1


def _install_legacy_ssh_compat() -> None:
    kex_info = paramiko.Transport._kex_info
    if _KexGroup14SHA1.name not in kex_info:
        kex_info[_KexGroup14SHA1.name] = _KexGroup14SHA1
    preferred_kex = paramiko.Transport._preferred_kex
    if _KexGroup14SHA1.name not in preferred_kex:
        paramiko.Transport._preferred_kex = (*preferred_kex, _KexGroup14SHA1.name)

    # group1 goes in last of all - see _KexGroup1SHA1.
    if _KexGroup1SHA1.name not in kex_info:
        kex_info[_KexGroup1SHA1.name] = _KexGroup1SHA1
    preferred_kex = paramiko.Transport._preferred_kex
    if _KexGroup1SHA1.name not in preferred_kex:
        paramiko.Transport._preferred_kex = (*preferred_kex, _KexGroup1SHA1.name)

    # ssh-rsa host keys: same RSA key blob format as rsa-sha2-*, paramiko
    # still implements RSAKey fully - it was only delisted as a host-key
    # *type* and its SHA-1 signature hash was dropped from RSAKey.HASHES.
    key_info = paramiko.Transport._key_info
    if "ssh-rsa" not in key_info:
        key_info["ssh-rsa"] = paramiko.RSAKey
    if "ssh-rsa" not in paramiko.rsakey.RSAKey.HASHES:
        paramiko.rsakey.RSAKey.HASHES["ssh-rsa"] = hashes.SHA1
    preferred_keys = paramiko.Transport._preferred_keys
    if "ssh-rsa" not in preferred_keys:
        paramiko.Transport._preferred_keys = (*preferred_keys, "ssh-rsa")


_install_legacy_ssh_compat()


class _QuietIncompatiblePeer(logging.Filter):
    """Drop paramiko's own log spam for a peer we cannot negotiate with.

    When key exchange finds no common algorithm, paramiko's transport thread logs
    "Exception (client): Incompatible ssh peer ..." and then the whole traceback
    line by line at ERROR - about 35 log records per poll cycle on this fleet,
    from the ~11 old Cisco switches (IOS 12.2(53-55)SE) that only offer
    diffie-hellman-group1-sha1 and are deliberately not supported here. The same
    failure is raised into our code, classified (_classify_ssh_error ->
    "protocol_error"), counted in ssh_operations_total and logged by the caller,
    so the transport thread's copy only buries real errors.

    Only that one thread's ERROR records are muted, and only after the
    "Incompatible ssh peer" line: the transport thread ends right after logging
    it, so nothing else is lost, and every other paramiko error still shows up.
    """

    def __init__(self) -> None:
        super().__init__()
        self._local = threading.local()

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.ERROR:
            return True
        if getattr(self._local, "muted", False):
            return False
        if "Incompatible ssh peer" in record.getMessage():
            self._local.muted = True
            return False
        return True


_transport_logger = logging.getLogger("paramiko.transport")
if not any(type(f).__name__ == "_QuietIncompatiblePeer" for f in _transport_logger.filters):
    _transport_logger.addFilter(_QuietIncompatiblePeer())
