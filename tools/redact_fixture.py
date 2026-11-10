"""Zero the controller serial number in captured JSONL files before they are committed as fixtures.

  python tools/redact_fixture.py capture-123.jsonl [more.jsonl ...]   # edits in place
The serial is bytes 6..9 of every HW_GET_INFO (0x0006) reply, which is the only place the library sends it.
"""
import json
import sys
from pathlib import Path

NOTE = "REDACTED: serial number bytes (offset 6, 4 bytes) replaced with zeros"
HW_GET_INFO_HEADER = bytes.fromhex("060054008150")  # id 0x0006, 84-byte data packet, from 0x50 to host


def redact(path: Path) -> int:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    hits = 0
    for row in rows:
        raw = bytes.fromhex(row["hex"])
        if row["dir"] == "rx" and raw.startswith(HW_GET_INFO_HEADER) and len(raw) >= 10:
            if raw[6:10] != bytes(4):
                hits += 1
            row["hex"] = (raw[:6] + bytes(4) + raw[10:]).hex()
            row["note"] = NOTE
    # A reply may be split across reads with the header in a later chunk; flag it instead of missing it silently.
    if not any(row.get("note") == NOTE for row in rows):
        raise SystemExit(f"{path}: no HW_GET_INFO reply found; check by hand")
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return hits


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for name in sys.argv[1:]:
        print(f"{name}: {redact(Path(name))} serial(s) redacted")
