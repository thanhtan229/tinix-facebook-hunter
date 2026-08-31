"""Shared API request conventions."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class ApiRequest(BaseModel):
    """Reject accidental fields and normalize surrounding whitespace."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def model_data(model: BaseModel, *, exclude_unset: bool = False) -> dict[str, Any]:
    return model.model_dump(exclude_unset=exclude_unset)
