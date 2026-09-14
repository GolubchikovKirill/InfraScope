from __future__ import annotations

import paramiko

from app.services.cisco_ssh import _KexGroup14SHA1


def test_legacy_group14_sha1_kex_is_registered():
    """Regression guard for the 63b92b1 paramiko 4->5 bump: that upgrade
    silently dropped every SHA-1 KEX algorithm, which is all the store
    fleet's old Cisco IOS switches speak, breaking every SSH path in this
    module (most visibly /camera-ports, which has no SNMP fallback unlike
    switch polling and port listing). If this ever stops being true after a
    future paramiko upgrade, cisco_ssh's own _install_legacy_ssh_compat
    patch has silently stopped applying."""
    assert paramiko.Transport._kex_info.get("diffie-hellman-group14-sha1") is _KexGroup14SHA1


def test_legacy_kex_is_lowest_priority():
    """The legacy algorithm must never outrank a modern one - it should only
    ever be picked when a peer offers nothing better."""
    preferred = paramiko.Transport._preferred_kex
    assert preferred[-1] == "diffie-hellman-group14-sha1"
    assert len(preferred) > 1


def test_legacy_ssh_rsa_host_key_is_registered():
    assert paramiko.Transport._key_info.get("ssh-rsa") is paramiko.RSAKey
    assert "ssh-rsa" in paramiko.rsakey.RSAKey.HASHES
    assert paramiko.Transport._preferred_keys[-1] == "ssh-rsa"
