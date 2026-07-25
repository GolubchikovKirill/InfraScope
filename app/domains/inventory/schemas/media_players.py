from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .common import _HOSTNAME_PATTERN, _normalize_mac, _validate_ip_or_hostname

__all__ = ["MediaPlayerCreate", "MediaPlayerUpdate", "MediaPlayerPublic", "MediaPlayersPublic"]


class MediaPlayerCreate(BaseModel):
    device_type: str
    name: str
    model: str = ""
    ip_address: str
    hostname: str | None = None
    mac_address: str | None = None

    @field_validator("device_type")
    @classmethod
    def validate_device_type(cls, v: str) -> str:
        if v not in ("nettop", "iconbit", "twix"):
            raise ValueError("device_type must be 'nettop', 'iconbit', or 'twix'")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("name must be 1-255 characters")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 255:
            raise ValueError("model must be <= 255 characters")
        return v

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        return _validate_ip_or_hostname(v)

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 255:
            raise ValueError("hostname must be <= 255 characters")
        if not re.match(_HOSTNAME_PATTERN, value):
            raise ValueError("hostname format is invalid")
        return value

    @field_validator("mac_address")
    @classmethod
    def validate_mac(cls, v: str | None) -> str | None:
        return _normalize_mac(v)

    @model_validator(mode="after")
    def set_default_model(self) -> MediaPlayerCreate:
        if not self.model:
            defaults = {"nettop": "Неттоп", "iconbit": "Iconbit", "twix": "Twix"}
            self.model = defaults.get(self.device_type, self.device_type)
        return self


class MediaPlayerUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    ip_address: str | None = None
    hostname: str | None = None
    mac_address: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v or len(v) > 255:
                raise ValueError("name must be 1-255 characters")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if len(v) > 255:
                raise ValueError("model must be <= 255 characters")
        return v

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_ip_or_hostname(v)
        return v

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        if len(value) > 255:
            raise ValueError("hostname must be <= 255 characters")
        if not re.match(_HOSTNAME_PATTERN, value):
            raise ValueError("hostname format is invalid")
        return value

    @field_validator("mac_address")
    @classmethod
    def validate_mac(cls, v: str | None) -> str | None:
        return _normalize_mac(v)


class MediaPlayerPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_type: str
    name: str
    model: str
    ip_address: str
    mac_address: str | None = None
    is_online: bool | None = None
    hostname: str | None = None
    os_info: str | None = None
    uptime: str | None = None
    open_ports: str | None = None
    last_polled_at: datetime | None = None
    created_at: datetime


class MediaPlayersPublic(BaseModel):
    data: list[MediaPlayerPublic]
    count: int
