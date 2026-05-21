# Publishing pydiylc

This file documents the manual release process. There's no CI publish flow
yet; both wheel and sdist are built locally and uploaded with twine.

## Prerequisites (one-time)

1. PyPI account at https://pypi.org with 2FA enabled.
2. Create an API token: PyPI → Account settings → API tokens → "Add API
   token", scope to "pydiylc" project (after the first manual upload).
3. Store the token in `~/.pypirc`:

   ```ini
   [pypi]
     username = __token__
     password = pypi-AgEI...your-token-here
   ```

   `chmod 600 ~/.pypirc`.

## Pre-flight checklist

Run from the repo root:

```bash
# 1. All tests green.
pytest -q

# 2. Catalog up to date.
python -m pydiylc.catalog > catalog.json
git diff catalog.json   # should be empty

# 3. CHANGELOG mentions the new version.
grep -q "^## v$(grep '^version' pyproject.toml | cut -d'"' -f2)" CHANGELOG.md

# 4. Version is bumped in both pyproject.toml and src/pydiylc/__init__.py.
grep "^version" pyproject.toml
grep "__version__" src/pydiylc/__init__.py

# 5. README hasn't gone stale (component table, recognition rate).
```

## Build and publish

```bash
rm -rf dist/ build/ *.egg-info
python -m build --wheel --sdist
twine check dist/*

# First, upload to TestPyPI:
twine upload --repository testpypi dist/*

# Verify it installs from TestPyPI:
python -m venv /tmp/pydiylc-test
/tmp/pydiylc-test/bin/pip install \
    --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    pydiylc
/tmp/pydiylc-test/bin/python -c "import pydiylc; print(pydiylc.__version__)"

# Then real PyPI:
twine upload dist/*
```

## Tag the release

```bash
VERSION=$(grep '^version' pyproject.toml | cut -d'"' -f2)
git tag -a "v$VERSION" -m "pydiylc $VERSION"
git push origin "v$VERSION"
```

## Post-release

- Create a GitHub Release pointing at the tag, paste the relevant
  `CHANGELOG.md` section into the body.
- Bump version in `pyproject.toml` and `__init__.py` to the next dev
  cycle (e.g. `0.3.0.dev0`).
