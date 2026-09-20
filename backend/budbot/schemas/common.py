"""Shared validation and serialization helpers for M2 schemas."""

import re
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
Industry = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
AddressLine = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=250)
]
City = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]
Region = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
PostalCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)
]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2}$")]

_PHONE_PATTERN = re.compile(r"^\+?[0-9().\- ]{7,40}$")


class DomainSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def validate_timezone(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return value


def validate_phone(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    digit_count = sum(character.isdigit() for character in normalized)
    if not _PHONE_PATTERN.fullmatch(normalized) or digit_count < 7:
        raise ValueError("phone contains unsupported characters or has invalid length")
    return normalized
