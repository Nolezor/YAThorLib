"""Reproducibly extract message identifiers and applicability, never infer layouts.

Requires pypdf only at development time. Body headings override contents errors;
conflicts remain in the generated audit file for review.
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    from pypdf import PdfReader
    pdf = ROOT / "docs/apt_communications_protocol.pdf"
    pages = [p.extract_text(extraction_mode="layout") or "" for p in PdfReader(pdf).pages]
    pattern = re.compile(r"^\s*(MGMSG_\s*[A-Z0-9_]+):?\s+(0[xX][0-9A-Fa-f]+)(?:\s+(\d+))?\s*$")
    observations, groups = {}, {}
    group = None
    for page, content in enumerate(pages, 1):
        for line in content.splitlines():
            if page <= 32 and line.startswith("Messages Applicable"):
                group = line.strip()
                groups.setdefault(group, [])
            match = pattern.match(line)
            if not match:
                continue
            name = re.sub(r"\s", "", match[1]).removeprefix("MGMSG_")
            observations.setdefault(name, []).append({"id": int(match[2], 16), "page": page,
                                                     "reference_page": int(match[3]) if match[3] else None})
            if page <= 32 and group and name not in groups[group]:
                groups[group].append(name)
    messages, conflicts = {}, []
    for name, rows in sorted(observations.items()):
        body = [r for r in rows if 50 <= r["page"] < 480 and r["reference_page"] is None]
        choices = body or rows
        ids = sorted({r["id"] for r in choices})
        if len(ids) > 1:
            conflicts.append({"name": name, "kind": "ambiguous-body", "observations": rows})
            # Preserve ambiguity, rather than silently emit a wrong command.
            continue
        selected = choices[0]
        messages[name] = {"id": selected["id"], "page": selected["reference_page"] or selected["page"],
                          "basis": "body-heading" if body else "contents-only"}
        if len({r["id"] for r in rows}) > 1:
            conflicts.append({"name": name, "kind": "body-overrides-contents", "observations": rows})
    out = ROOT / "src/yathorlib/data"
    out.mkdir(parents=True, exist_ok=True)
    result = {"source": pdf.name, "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
              "issue": 48, "messages": messages, "groups": groups, "conflicts": conflicts}
    (out / "catalog.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"{len(messages)} identifiers; {len(groups)} applicability groups; {len(conflicts)} conflicts")


if __name__ == "__main__":
    build()
