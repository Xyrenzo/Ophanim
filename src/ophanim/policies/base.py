"""Minimal policy interface shared by every baseline and adapter."""

from __future__ import annotations

from typing import Protocol


class Policy(Protocol):
    name: str

    def reset(self, observation: dict, info: dict) -> None:
        """Called once with the reset observation."""

    def act(self, observation: dict) -> dict:
        """Return the next JSON action given the latest observation."""


def list_action(table: str, cursor: str | None, limit: int = 50) -> dict:
    return {"action": "list_records", "table": table, "cursor": cursor, "limit": limit}


def submit_action(episode_id: str, findings: list[dict]) -> dict:
    return {"action": "submit", "findings": {"episode_id": episode_id, "findings": findings}}
