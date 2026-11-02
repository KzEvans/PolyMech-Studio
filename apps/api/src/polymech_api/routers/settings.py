"""User settings (non-secret) and secrets status (values are never returned)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from polymech_api import secrets_store
from polymech_api.deps import get_state
from polymech_api.state import AppState

router = APIRouter(prefix="/api", tags=["settings"])
State = Annotated[AppState, Depends(get_state)]


@router.get("/settings")
def read(state: State) -> dict[str, Any]:
    return state.settings() | {
        "data_dir": "（本机应用数据目录）",
        "secrets": {k: secrets_store.has_secret(k) for k in secrets_store.ENV},
    }


@router.put("/settings")
def write(state: State, patch: dict[str, Any]) -> dict[str, Any]:
    state.update_settings(patch)
    return read(state)


class SecretIn(BaseModel):
    name: Literal["bridge_token", "anthropic_api_key", "openai_api_key"]
    value: str


@router.post("/settings/secrets")
def set_secret(body: SecretIn) -> dict[str, bool]:
    secrets_store.set_secret(body.name, body.value)
    return {"configured": True}
