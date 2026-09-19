from __future__ import annotations

import paramiko

from app.services.cisco_ssh import _KexGroup1SHA1, _KexGroup14SHA1


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
    # group1 (1024-bit) is the weakest and must come after group14-sha1, which
    # in turn comes after everything modern
    assert preferred[-1] == "diffie-hellman-group1-sha1"
    assert preferred[-2] == "diffie-hellman-group14-sha1"
    assert len(preferred) > 2


def test_legacy_ssh_rsa_host_key_is_registered():
    assert paramiko.Transport._key_info.get("ssh-rsa") is paramiko.RSAKey
    assert "ssh-rsa" in paramiko.rsakey.RSAKey.HASHES
    assert paramiko.Transport._preferred_keys[-1] == "ssh-rsa"


def test_legacy_group1_sha1_kex_is_registered():
    assert paramiko.Transport._kex_info.get("diffie-hellman-group1-sha1") is _KexGroup1SHA1
    assert _KexGroup1SHA1.name == "diffie-hellman-group1-sha1"


def test_group1_uses_sha1_and_generator_2():
    import hashlib

    assert _KexGroup1SHA1.hash_algo is hashlib.sha1
    assert _KexGroup1SHA1.G == 2


def _pi_scaled(bits: int) -> int:
    """pi * 2**bits by Machin's formula in integer arithmetic."""
    scale = 1 << (bits + 64)

    def atan_inv(x: int) -> int:
        total = term = scale // x
        x2, n, sign = x * x, 3, -1
        while term:
            term //= x2
            total += sign * (term // n)
            n += 2
            sign = -sign
        return total

    return (4 * (4 * atan_inv(5) - atan_inv(239))) >> 64


def _is_probable_prime(n: int, rounds: int = 16) -> bool:
    import random

    for small in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % small == 0:
            return n == small
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        x = pow(random.randrange(2, n - 1), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def test_group1_prime_is_the_rfc_2409_oakley_group_2_and_a_safe_prime():
    """The modulus is a security-critical constant typed into the source, so
    prove it instead of trusting it: RFC 2409 section 6.2 defines it as
    2**1024 - 2**960 - 1 + 2**64 * (floor(2**894 * pi) + 129093), and a DH
    modulus must be a safe prime (p and (p-1)/2 both prime)."""
    p = _KexGroup1SHA1.P

    assert p.bit_length() == 1024
    assert p == (1 << 1024) - (1 << 960) - 1 + (1 << 64) * (_pi_scaled(894) + 129093)
    assert _is_probable_prime(p)
    assert _is_probable_prime((p - 1) // 2)


def test_group1_generates_a_private_exponent_inside_the_group_order():
    class _FakeTransport:
        server_mode = False

    kex = _KexGroup1SHA1(_FakeTransport())
    kex._generate_x()

    assert 1 < kex.x < (_KexGroup1SHA1.P - 1) // 2
