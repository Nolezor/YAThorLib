# Changelog

## Unreleased

- Vendor files (`REA Source/`) removed from git and ignored; history rewritten.
- `Connection.reserve_updates()` replaces direct access to private state from `Device.updates`.
- Ruff and mypy added to development tooling and CI.

## 0.1.0

- Initial alpha: asyncio APT transport, command catalog, selected typed device APIs. No hardware validation.
