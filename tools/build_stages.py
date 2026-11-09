"""Derive the KDC101/TDC001 stage table from Kinesis' ThorlabsDefaultSettings.xml.

The XML is vendor material kept local in 'REA Source/' (git-ignored). Only the derived numbers are written
to src/yathorlib/data/stages.json. Counts per unit = StepsPerRev * GearboxRatio / Pitch, the formula that
reproduces the protocol PDF's EncCnt table for the Z8 and PRM1 stages (p.42); stages where it does not
(Z6xx, CR1-Z7) are listed as mismatches so nobody trusts them blindly.
"""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "REA Source/Thorlabs/ThorlabsDefaultSettings.xml"
OUT = ROOT / "src/yathorlib/data/stages.json"
CONTROLLERS = ("KDC101", "TDC001")
UNITS = {"1": "mm", "2": "deg"}
# EncCnt per mm or per degree, protocol PDF issue 48 p.42, brushed DC table.
PDF = {"MTS25-Z8": 34554.96, "MTS50-Z8": 34554.96, "Z8xx": 34554.96, "Z6xx": 24600,
       "PRM1-Z8": 1919.6418578623391, "CR1-Z7": 12288}


def main() -> None:
    raw = SOURCE.read_bytes()
    root = ET.fromstring(raw)
    definitions: dict[str, list[ET.Element]] = {}
    for d in root.iter("DeviceSettingsDefinition"):
        definitions.setdefault(d.get("Name"), []).append(d)
    stages, skipped = {}, []
    for dev in root.iter("DeviceType"):
        if dev.get("Name") not in CONTROLLERS:
            continue
        for entry in dev.iter("DeviceSettingsType"):
            name, target = entry.get("Name"), entry.get("Settings") or entry.get("Name")
            phys = [p for d in definitions.get(target, []) if (p := d.find("Physical")) is not None]
            if len(phys) != 1 or phys[0].findtext("Units") not in UNITS:
                skipped.append(name)
                continue
            p = phys[0]
            pitch, steps, gear = (float(p.findtext(k)) for k in ("Pitch", "StepsPerRev", "GearboxRatio"))
            record = {"settings": target, "units": UNITS[p.findtext("Units")], "pitch": pitch,
                      "steps_per_rev": steps, "gearbox_ratio": gear, "counts_per_unit": steps * gear / pitch,
                      "min_pos": float(p.findtext("MinPos")), "max_pos": float(p.findtext("MaxPos")),
                      "max_vel": float(p.findtext("MaxVel")), "max_acc": float(p.findtext("MaxAccn"))}
            if stages.setdefault(name, record) != record:
                raise SystemExit(f"{name}: conflicting definitions across controllers")
    mismatches = {n: {"derived": stages[n]["counts_per_unit"], "pdf": v} for n, v in PDF.items()
                  if n in stages and abs(stages[n]["counts_per_unit"] - v) > 1e-6 * v}
    OUT.write_text(json.dumps({
        "source": {"file": SOURCE.name, "version": root.find("Info").get("Version"),
                   "sha256": hashlib.sha256(raw).hexdigest()},
        "note": "Derived from vendor settings; encoder-fitted variants (e.g. KMTS..E) are not listed unless Kinesis lists them.",
        "pdf_mismatches": mismatches, "stages": dict(sorted(stages.items()))}, indent=1) + "\n")
    print(f"{len(stages)} stages, {len(skipped)} skipped {skipped}, PDF mismatches: {mismatches}")


if __name__ == "__main__":
    main()
