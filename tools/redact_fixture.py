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
    # Replies can arrive split across reads, so search the whole rx byte stream and map back to the chunks.
    rx = [row for row in rows if row["dir"] == "rx"]
    stream = bytearray(b"".join(bytes.fromhex(row["hex"]) for row in rx))
    hits, found = 0, 0
    i = stream.find(HW_GET_INFO_HEADER)
    while i != -1 and i + 10 <= len(stream):
        found += 1
        hits += stream[i + 6:i + 10] != bytes(4)
        stream[i + 6:i + 10] = bytes(4)
        i = stream.find(HW_GET_INFO_HEADER, i + 10)
    if not found:
        raise SystemExit(f"{path}: no HW_GET_INFO reply found; check by hand")
    start = 0
    for row in rx:
        size = len(row["hex"]) // 2
        row["hex"] = bytes(stream[start:start + size]).hex()
        start += size
    rx[0]["note"] = NOTE  # the zeroed bytes may sit in a later chunk, so mark the stream's first row
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return hits


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for name in sys.argv[1:]:
        print(f"{name}: {redact(Path(name))} serial(s) redacted")
