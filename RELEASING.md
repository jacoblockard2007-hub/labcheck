# Releasing labcheck

The primary distribution channel is **GitHub Releases**. When a release is
published, the `release` workflow builds the sdist, wheel and `SHA256SUMS`, and
attaches them to that release. Users install with:

```bash
python3 -m pip install \
  https://github.com/jacoblockard2007-hub/labcheck/releases/latest/download/labcheck-X.Y.Z-py3-none-any.whl
```

PyPI publication is optional. The `publish` workflow is ready for
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) and is triggered
manually once the one-time PyPI setup below is complete.

## Cutting a release

1. Update the version in `pyproject.toml` and `labcheck/__init__.py`, and bump
   the wheel filename in the README quick-start command.
2. Add an entry to `CHANGELOG.md`.
3. Run the local checks:

   ```bash
   make check
   python3 -m compileall -q labcheck
   ```

4. Commit, tag and push:

   ```bash
   git add -A
   git commit -m "Release X.Y.Z"
   git tag -a vX.Y.Z -m "labcheck X.Y.Z"
   git push origin main --tags
   ```

5. Create a GitHub release for the tag:

   ```bash
   gh release create vX.Y.Z --title "labcheck X.Y.Z" --notes-file CHANGELOG.md
   ```

   Publishing the release triggers the `release` workflow, which attaches
   `labcheck-X.Y.Z-py3-none-any.whl`, `labcheck-X.Y.Z.tar.gz` and
   `SHA256SUMS`. Watch it with `gh run watch`.

6. Verify the assets and install the wheel in a clean environment:

   ```bash
   python3 -m venv /tmp/labcheck-check
   /tmp/labcheck-check/bin/pip install \
     https://github.com/jacoblockard2007-hub/labcheck/releases/download/vX.Y.Z/labcheck-X.Y.Z-py3-none-any.whl
   /tmp/labcheck-check/bin/labcheck --version
   ```

## Optional: PyPI

Only needed if you want `pip install labcheck` to work without a URL.

1. Create an account at <https://pypi.org/account/register/> and enable
   two-factor authentication.
2. Open <https://pypi.org/manage/account/publishing/> and add a **pending
   publisher** with:
   - PyPI project name: `labcheck`
   - Owner: `jacoblockard2007-hub`
   - Repository name: `labcheck`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`

   The `pypi` environment already exists in the GitHub repository.
3. Trigger the upload manually after the pending publisher exists:

   ```bash
   gh workflow run publish.yml
   gh run watch
   ```

4. Confirm the files on <https://pypi.org/project/labcheck/>.

The workflow is intentionally `workflow_dispatch` only until PyPI is configured,
so creating a GitHub release never fails on an unpublished project. Once the
publisher works, add `release: types: [published]` to `publish.yml` if you want
automatic PyPI uploads.

### Manual PyPI upload

If Actions is unavailable, build and upload from a checkout. Use a PyPI API
token scoped to `labcheck`; `twine` prompts for it, so it does not need to be
stored anywhere.

```bash
python3 -m build
python3 -m twine upload dist/*
```
