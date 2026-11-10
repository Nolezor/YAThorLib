# Contributing

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check . && mypy src
```

- Never commit Thorlabs binaries, drivers, headers or PDF text. `REA Source/` is git-ignored.
- Capture hardware sessions with `tools/hw_check.py`, then run `python tools/redact_fixture.py capture-*.jsonl` (zeroes the controller serial) and put the files under `tests/fixtures/hardware/<model>/` with a replay test.
- A new typed device API needs a synthetic test and a `docs/support.md` row.
- Claiming a model works needs hardware evidence: a raw TX/RX capture, the model, firmware version and what was exercised. Do not infer stage scale or limits from a controller model; cite the source.
