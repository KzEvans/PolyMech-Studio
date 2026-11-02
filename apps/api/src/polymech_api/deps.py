"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from polymech_api.state import AppState


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.polymech
    return state
