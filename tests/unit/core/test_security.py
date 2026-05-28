from app.core.security import get_password_hash, needs_rehash, verify_password


def test_password_hash_and_verify_roundtrip():
    hashed = get_password_hash("Pass1234")
    assert verify_password("Pass1234", hashed) is True
    assert verify_password("Wrong1234", hashed) is False


def test_argon_hash_does_not_need_rehash_immediately():
    hashed = get_password_hash("Pass1234")
    assert needs_rehash(hashed) is False
