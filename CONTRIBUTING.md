# Contributing to labcheck

Thanks for taking a look. Bug reports, check ideas and patches are welcome.

## Reporting a problem

Please include:

- the output of `labcheck --version`;
- your distribution and Python version (`python3 --version`);
- the failing check in verbose mode, e.g. `labcheck --only storage -v`;
- the relevant part of your config, with secrets removed.

If a check crashes, run with `-v --json`; the JSON report includes the traceback
in the check details.

## Development

There is nothing to install for development: the runtime is standard-library
only and the tests are plain `unittest`.

```bash
git clone <your-fork>
cd labcheck
python3 -m unittest discover -s tests -t . -v
python3 -m labcheck --list-checks
python3 -m labcheck -v
```

Optional, if you have Ruff installed:

```bash
ruff check labcheck tests
ruff format --check labcheck tests
```

With `make` and Ruff available, `make check` runs tests, lint and formatting in
one go.

Please report security problems privately as described in
[SECURITY.md](SECURITY.md), not in a public issue.

## Adding a check

1. Create `labcheck/checks/yourcheck.py` exposing `NAME`, `TITLE`,
   `DESCRIPTION` and `run(ctx) -> CheckResult`.
2. Add a config section in `labcheck/config.py` if the check needs settings,
   and register the section in `_SECTION_KEYS`.
3. Register the check in `labcheck/checks/__init__.py`. The `config_key`
   field points at the section that controls `enabled`.
4. Add tests under `tests/`. Parser tests should use plain strings; check tests
   should use `FakeRunner` and temporary `/proc` trees from `tests/helpers.py`.
5. Update `README.md` and `labcheck.example.toml`.

## Rules of the road

- **Standard library only.** A new runtime dependency needs a very good reason.
- **Read-only.** Checks may query the system but must not modify it.
- **Never raise for expected conditions.** Missing tools, permissions and
  unreadable files should produce `SKIP` or `ERROR`, not a traceback.
- **Use the injected context.** Read through `ctx.proc`, `ctx.sys`, `ctx.root`,
  `ctx.runner` and `ctx.now` so checks remain testable.
- **No shell.** Pass argument lists to `ctx.runner.run`; never build a shell
  command from config values.
- **Keep output formats stable.** Metrics are part of the public interface;
  additive changes are preferred.
- **Format with Ruff** if it is available, and keep Python 3.11 compatibility.

## Pull requests

Small, focused pull requests are easiest to review. Include tests for new
behaviour and mention any user-visible change in `CHANGELOG.md`.

Maintainers cutting a release should follow [RELEASING.md](RELEASING.md).

By contributing, you agree that your contribution is licensed under the MIT
license in `LICENSE`.
