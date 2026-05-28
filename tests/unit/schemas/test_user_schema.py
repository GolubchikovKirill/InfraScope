import pytest
from pydantic import ValidationError

from app.schemas import UserCreate


def test_user_create_requires_strong_password():
    with pytest.raises(ValidationError):
        UserCreate(email="user@example.com", password="12345678")


def test_user_create_accepts_valid_password():
    model = UserCreate(email="user@example.com", password="Pass1234")
    assert model.email == "user@example.com"
