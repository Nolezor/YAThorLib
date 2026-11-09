"""Documented command names and controller applicability, with source pages."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import IntEnum
from importlib.resources import files

_DATA = json.loads(files("yathorlib").joinpath("data/catalog.json").read_text())
_NATIVE = json.loads(files("yathorlib").joinpath("data/native.json").read_text())
_MESSAGES = _DATA["messages"] | _NATIVE["messages"]
# members come from data at import time, which mypy cannot see
MessageID = IntEnum("MessageID", {k: v["id"] for k, v in _MESSAGES.items()}, module=__name__)  # type: ignore[misc]


@dataclass(frozen=True)
class Command:
    name: str
    id: int
    page: int | None
    basis: str


COMMANDS = {name: Command(name, **value) for name, value in _MESSAGES.items()}
GROUPS = {name: frozenset(values) for name, values in _DATA["groups"].items()}


def command(name: str | int) -> Command:
    if isinstance(name, str):
        return COMMANDS[name.removeprefix("MGMSG_").upper()]
    choices = [c for c in COMMANDS.values() if c.id == name]
    if len(choices) != 1:
        raise ValueError("numeric ID has aliases or is unknown; supply an exact command name")
    return choices[0]


def commands_for(model: str) -> frozenset[str]:
    """Union all matching contents groups, including model-specific additions.

    'x' in a family is a single digit; e.g. BBD30x includes BBD301.
    Unknown models fail explicitly. Applicability is documentation, not hardware QA.
    """
    model = model.upper()
    if model in _NATIVE["models"]:
        return frozenset(_NATIVE["models"][model])
    result: set[str] = set()
    for heading, names in GROUPS.items():
        tokens = re.findall(r"\b[A-Z][A-Za-z]*[0-9][A-Za-z0-9]*\b|\bLTS\b|\bGNMx\b", heading)
        for token in tokens:
            pattern = re.escape(token).replace("x", "[0-9]").upper()
            if token == "LTS":
                pattern = r"LTS[0-9]+"
            if re.fullmatch(pattern, model):
                result.update(names)
    if not result:
        raise ValueError(f"no documented applicability group for {model!r}")
    return frozenset(result & COMMANDS.keys())
