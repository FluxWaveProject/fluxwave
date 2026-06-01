# Hosting Documentation Online

FluxWave docs are written in Markdown and built with Sphinx. You can publish
them with ReadTheDocs or GitHub Pages.

## Quick Links

- [Build Locally](#build-locally)
- [ReadTheDocs](#readthedocs)
- [GitHub Pages](#github-pages)
- [What to Publish](#what-to-publish)

## Build Locally

```bash
python -m pip install -e ".[docs]"
python -m sphinx -b html docs docs/_build/html
```

Open:

```text
docs/_build/html/index.html
```

`docs/_build/html` is generated output. Do not edit files there directly.
Change the Markdown files in `docs/`, then rebuild.

## ReadTheDocs

Recommended for Python libraries. ReadTheDocs builds from the `.readthedocs.yaml`
file in the repository root (already included), so there is no build command to
configure in the web UI.

1. Push the repository to GitHub (it already contains `.readthedocs.yaml`, which
   pins Python, points Sphinx at `docs/conf.py`, and installs the `docs` extra).
2. Sign in at <https://app.readthedocs.org> with your GitHub account.
3. Click **Add project**, select the `fluxwave` repository, and confirm. The
   default slug becomes the URL, e.g. `https://fluxwave.readthedocs.io`.
4. ReadTheDocs reads `.readthedocs.yaml` and builds automatically; every push to
   the default branch triggers a rebuild. Watch the first build under the
   project's **Builds** tab.
5. Optionally enable **pull-request builds** in the project settings so docs are
   previewed on PRs.
6. Once the docs URL is live, set it as `Documentation` in `pyproject.toml`'s
   `[project.urls]`.

The included `.readthedocs.yaml`:

```yaml
version: 2
build:
  os: ubuntu-24.04
  tools:
    python: "3.12"
sphinx:
  configuration: docs/conf.py
python:
  install:
    - method: pip
      path: .
      extra_requirements:
        - docs
formats:
  - pdf
```

## GitHub Pages

Recommended when you want docs under the same GitHub repository.

One simple workflow:

```yaml
name: Docs

on:
  push:
    branches: [main]

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python -m pip install -e ".[docs]"
      - run: python -m sphinx -b html docs docs/_build/html
      - uses: actions/upload-pages-artifact@v3
        with:
          path: docs/_build/html

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

Enable GitHub Pages in repository settings and choose GitHub Actions as the
source.

## What to Publish

Publish generated HTML from:

```text
docs/_build/html
```

Keep source docs in Git:

```text
docs/*.md
docs/guide/*.md
docs/api/index.md
docs/conf.py
```

Do not commit generated `_build` output unless you intentionally use a static
branch workflow.
