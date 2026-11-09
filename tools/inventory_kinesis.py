"""Inventory supplied binaries/headers and optionally retain REA native exports.

Usage: python tools/inventory_kinesis.py [--rea /absolute/path/to/rea]
Never loads or executes a supplied DLL.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rea")
    args = parser.parse_args()
    source = ROOT / "REA Source/Thorlabs"
    out = ROOT / "docs/research/native-exports"
    out.mkdir(exist_ok=True, parents=True)
    records = []
    for path in sorted(source.iterdir()):
        if path.suffix.lower() not in (".dll", ".h", ".xml"):
            continue
        content = path.read_bytes()
        record = {"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(content).hexdigest(),
                  "bytes": len(content)}
        if path.suffix == ".h":
            text = content.decode("utf-8-sig", "replace")
            record["declared_functions"] = sorted(set(re.findall(r"\b([A-Z][A-Z0-9]*_[A-Za-z0-9_]+)\s*\(", text)))
            record["declared_structs"] = sorted(set(re.findall(r"\bstruct\s+(\w+)", text)))
            record["coverage"] = "header-declarations-only"
        elif args.rea and path.suffix == ".dll" and not any(x in path.name for x in ("CLI", "UI", "Tools.", "Xceed")):
            output = out / (path.stem + ".json")
            if not output.exists():
                result = subprocess.run([args.rea, "inspect-native-exports", str(path), "--json"],
                                        capture_output=True, text=True, timeout=120)
                output.write_text(result.stdout)
            try:
                evidence = json.loads(output.read_text())
                normalized = evidence["normalized_result"]
                record.update(evidence_id=evidence["evidence_id"],
                              exports=len(normalized["exports"]), coverage=normalized["coverage"])
            except (KeyError, ValueError):
                record["coverage"] = "failed-see-export-file"
        records.append(record)
    result = {"authority": "shipped-artifact", "files": records,
              "limitations": ["Exports and header declarations do not establish wire-level behavior.",
                              "Only top-level supplied DLLs, headers and XML files are inventoried."]}
    (ROOT / "docs/research/inventory.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"Inventoried {len(records)} files")


if __name__ == "__main__":
    main()
