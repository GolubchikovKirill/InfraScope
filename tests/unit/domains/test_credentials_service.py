"""Password generator: class toggles, exclusions, the one-of-each guarantee."""

import string

import pytest

from app.domains.credentials.schemas import PasswordGenerateRequest
from app.domains.credentials.service import AMBIGUOUS, SYMBOLS, generate_password


def _req(**kw) -> PasswordGenerateRequest:
    return PasswordGenerateRequest(**kw)


def test_length_is_honoured():
    pw, _ = generate_password(_req(length=37))
    assert len(pw) == 37


def test_disabled_classes_are_absent():
    pw, _ = generate_password(
        _req(length=64, uppercase=True, lowercase=False, digits=False, symbols=False)
    )
    assert set(pw) <= set(string.ascii_uppercase)


def test_symbols_only_uses_the_curated_set():
    pw, _ = generate_password(
        _req(length=64, uppercase=False, lowercase=False, digits=False, symbols=True)
    )
    assert set(pw) <= set(SYMBOLS)
    # never the quoting-hazard characters
    assert not (set(pw) & set("\"'\\ |`"))


def test_min_of_each_guarantees_every_enabled_class():
    # length 8 == 2 * the 4 classes, so the guarantee is the only reason every
    # class would always appear
    for _ in range(50):
        pw, _ = generate_password(_req(length=8, min_of_each=True))
        assert any(c in string.ascii_uppercase for c in pw)
        assert any(c in string.ascii_lowercase for c in pw)
        assert any(c in string.digits for c in pw)
        assert any(c in SYMBOLS for c in pw)


def test_min_of_each_off_allows_a_missing_class():
    # with the guarantee off, a short 2-class password can legally miss a class;
    # over many draws at least one will (P(no digit in 8 of 36) ~= 0.075)
    missed = any(
        not any(
            c in string.digits
            for c in generate_password(
                _req(length=8, uppercase=False, symbols=False, min_of_each=False)
            )[0]
        )
        for _ in range(300)
    )
    assert missed


def test_exclude_ambiguous_strips_confusable_characters():
    for _ in range(20):
        pw, _ = generate_password(_req(length=128, exclude_ambiguous=True))
        assert not (set(pw) & set(AMBIGUOUS))


def test_exclude_chars_is_respected():
    pw, _ = generate_password(_req(length=128, exclude_chars="abcABC123"))
    assert not (set(pw) & set("abcABC123"))


def test_no_classes_selected_raises():
    with pytest.raises(ValueError):
        generate_password(
            _req(uppercase=False, lowercase=False, digits=False, symbols=False)
        )


def test_all_characters_excluded_raises():
    with pytest.raises(ValueError):
        generate_password(
            _req(
                length=12,
                uppercase=False,
                lowercase=True,
                digits=False,
                symbols=False,
                exclude_chars=string.ascii_lowercase,
            )
        )


def test_length_too_short_for_min_of_each_raises():
    with pytest.raises(ValueError):
        generate_password(_req(length=3, min_of_each=True))  # 4 classes, 3 slots


def test_entropy_grows_with_length():
    _, short = generate_password(_req(length=12))
    _, long = generate_password(_req(length=48))
    assert long > short > 0
