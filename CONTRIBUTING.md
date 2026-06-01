# Contributing to FluxWave

Thanks for your interest in improving FluxWave! This guide covers the local
setup and the checks every change must pass.

## Development setup

FluxWave targets Python 3.11+. Clone the repo and install the dev extras into a
virtual environment:

```bash
git clone https://github.com/FluxWaveProject/fluxwave.git
cd fluxwave
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev,docs]"
```

The `dev` extra installs `discord.py` so the test suite has a Discord library to
run against. FluxWave itself works with discord.py, py-cord, nextcord, or disnake.

## Checks

CI runs these on every push and pull request (Python 3.11–3.14). Run them locally
before opening a PR:

```bash
ruff check .            # lint
ruff format --check .   # formatting
mypy                    # strict type checking
pytest                  # unit tests
```

`ruff format .` will auto-format your changes.

## Tests

- Unit tests live in `tests/` and must not require a network connection.
- Add or update tests for any behavior change; bug fixes should include a
  regression test that fails before the fix.
- Integration tests are marked `@pytest.mark.integration` and require a real
  Lavalink v4 server:

  ```bash
  LAVALINK_HOST=127.0.0.1 LAVALINK_PORT=2333 LAVALINK_PASSWORD=youshallnotpass \
  LAVALINK_SECURE=false pytest -m integration tests/test_integration_lavalink.py
  ```

## Pull requests

1. Branch off `main`.
2. Keep changes focused; one logical change per PR.
3. Make sure all four checks above pass and docs are updated if you changed the
   public API.
4. Describe what changed and why in the PR body.

## Reporting bugs

Open a [GitHub issue](https://github.com/FluxWaveProject/fluxwave/issues)
with FluxWave/Python/Lavalink versions, a minimal reproduction, and the full
traceback. Never paste real bot tokens or Lavalink passwords.

## Code style

- Strictly typed (`mypy --strict`, `py.typed`); add precise type hints.
- Match the surrounding code's naming and structure.
- Public API additions should be exported from `fluxwave/__init__.py` and
  documented under `docs/`.
