"""KDC101/TDC001 stage table derived from Kinesis settings (see tools/build_stages.py)."""
import json
from importlib.resources import files

from .codecs import UnitScale

_DATA = json.loads(files("yathorlib").joinpath("data/stages.json").read_text())
STAGES: dict[str, dict] = _DATA["stages"]


# Thorlabs sells the MTS100/M-Z8 stage with a KDC101 as KMTS100E/M (manual 19593-D02 is shown on its page;
# identity and the 34555 counts/mm scale confirmed by the owner with a physical distance measurement, 2026-11-10).
ALIASES = {"KMTS100E/M": "MTS100/M-Z8"}


def stage_scale(name: str) -> UnitScale:
    """Scale for a stage Kinesis lists for the KDC101/TDC001. Unknown names are rejected, never guessed.

    Position unit is mm or degrees per STAGES[name]['units']. Check the stage matches what is attached:
    an encoder-fitted variant can differ from the plain stage with a similar name.
    """
    try:
        return UnitScale.for_dc_servo(STAGES[ALIASES.get(name, name)]["counts_per_unit"])
    except KeyError:
        raise KeyError(f"{name!r} is not in the Kinesis KDC101/TDC001 stage table") from None
