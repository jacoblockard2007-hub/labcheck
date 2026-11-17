# Releasing labcheck

Releases are published to PyPI by GitHub Actions using
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/), so no API
tokens or secrets are stored in the repository.

## One-time PyPI setup

1. Create an account at <https://pypi.org/account/register/> if needed and
   enable two-factor authentication.
2. Open <https://pypi.org/manage/account/publishing/> and add a **pending
   publisher** with:
   - PyPI project name: `labcheck`
   - Owner: `jacoblockard2007-hub`
   - Repository name: `labcheck`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`

The `pypi` environment already exists in the GitHub repository.

## Cutting a release

1. Update the version in `pyproject.toml` and `labcheck/__init__.py`.
2. Add an entry to `CHANGELOG.md`.
3. Run the local checks:

   ```bash
   python3 -m unittest discover -s tests -t . -v
   python3 -m compileall -q labcheck
   ```

4. Commit, tag and push:

   ```bash
   git add -A
   git commit -m "Release X.Y.Z"
   git tag -a vX.Y.Z -m "labcheck X.Y.Z"
   git push origin main --tags
   ```

5. Create a GitHub release for the tag. Publishing the release triggers the
   `publish` workflow, which builds the sdist and wheel and uploads them to
   PyPI.

   ```bash
   gh release create vX.Y.Z --title "labcheck X.Y.Z" --notes-file CHANGELOG.md
   ```

6. Confirm the new files on <https://pypi.org/project/labcheck/> and install
   from PyPI in a clean environment:

   ```bash
   python3 -m venv /tmp/labcheck-check
   /tmp/labcheck-check/bin/pip install labcheck==X.Y.Z
   /tmp/labcheck-check/bin/labcheck --version
   ```

## Manual publishing

If the workflow is unavailable, build and upload from a checkout. Use a PyPI
API token scoped to the `labcheck` project; `twine` prompts for it, so it does
not need to be stored anywhere.

```bash
python3 -m build
python3 -m twine upload dist/*
```
