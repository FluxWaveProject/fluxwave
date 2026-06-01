# Testing and Release

## Quick Links

- [Local Quality Gate](#local-quality-gate)
- [Docs Build](#docs-build)
- [Publish Docs Online](#publish-docs-online)
- [Lavalink Integration Tests](#lavalink-integration-tests)
- [Real Discord Soak Checklist](#real-discord-soak-checklist)
- [Build Package](#build-package)
- [Release Workflow](#release-workflow)
- [Versioning](#versioning)

## Local Quality Gate

Run before every commit:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest
```

Debug environment output:

```bash
python -m fluxwave --version
```

## Docs Build

```bash
.venv/bin/python -m pip install -e ".[docs]"
.venv/bin/python -m sphinx -b html docs docs/_build/html
```

Generated HTML is ignored by Git.

## Publish Docs Online

See [Hosting Documentation Online](hosting.md) for ReadTheDocs and GitHub Pages
deployment options.

## Lavalink Integration Tests

Integration tests require a live Lavalink server:

```bash
LAVALINK_HOST=127.0.0.1 \
LAVALINK_PORT=2333 \
LAVALINK_PASSWORD=youshallnotpass \
LAVALINK_SECURE=false \
.venv/bin/python -m pytest -m integration tests/test_integration_lavalink.py
```

## Real Discord Soak Checklist

Before a stable release, test with a real bot:

- Lavalink restart while playing.
- Voice channel move spam.
- Skip/stop spam in loop mode.
- 50+ track playlist queue.
- Bot kicked while playing.
- Playlist plus autoplay together.
- Node failover with active players.
- Filter changes during playback.
- Lyrics/plugin routes.
- Save state, restart bot, restore state.

## Build Package

```bash
.venv/bin/python -m pip install build
.venv/bin/python -m build
```

Artifacts are written to `dist/`.

## Release Workflow

The repository includes `.github/workflows/release.yml`, triggered by tags that
start with `v`.

Example:

```bash
git tag v0.2.0
git push origin v0.2.0
```

The workflow builds distributions, publishes them to PyPI through trusted
publishing, and creates a GitHub release with the built artifacts.

## Versioning

Current version: `0.2.0`.

Before `1.0`, public APIs may change. After `1.0`, breaking changes should use
a major version bump.
