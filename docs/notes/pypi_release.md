# PyPI first release (agent-memory-labs)

Notes for a first public release of `D:\code\agentic-memory`. The clean path is below.

---

## Version

Pick an intentional first public version. Recommendations:

| Situation | Suggested version |
|-----------|-------------------|
| Deliberate first public beta | **0.2.0** |
| Smallest change from current local versioning | **0.1.5** |

Do **not** use `0.2.2` unless this repo already had public `0.2.1` (it does not).

---

## Package name

This is the real first blocker.

1. **Verify** whether `agent-memory-labs` on PyPI is available.
2. If it is **not**, choose one of:
   - An `agentic-codememory`-style alternate package name
   - Another new package name you control

You can still expose the CLI command as `agent-memory` even if the PyPI package name differs.

---

## Build

From this repo:

```powershell
cd D:\code\agentic-memory
.\.venv-agentic-memory\Scripts\python.exe -m pip install --upgrade build twine
.\.venv-agentic-memory\Scripts\python.exe -m build
.\.venv-agentic-memory\Scripts\twine.exe check dist/*
```

That should produce:

- **sdist**
- **wheel**

---

## Smoke test the built package

Before publishing, install the built wheel into a clean env or with **pipx** and verify:

```powershell
pipx install .\dist\YOUR_WHEEL.whl
agent-memory --help
agent-memory status --json
agent-memory serve --help
```

Also verify in a **separate repo** that the current UX is acceptable:

- `init`
- `index`
- `serve`

**Especially important:**

- `index` currently depends on the **working directory** for repo targeting
- `serve` supports `--repo` and `--env-file`
- If that is good enough for first release, ship it; if not, fix it before release

---

## TestPyPI first

Recommended for a first release:

```powershell
.\.venv-agentic-memory\Scripts\twine.exe upload --repository testpypi dist/*
```

Then verify install from TestPyPI in another environment:

```powershell
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple YOUR_PACKAGE_NAME
```

**Check:**

- CLI installs cleanly
- Entry points exist
- Import path works
- Docs match reality

---

## PyPI release

Once TestPyPI passes:

```powershell
.\.venv-agentic-memory\Scripts\twine.exe upload dist/*
```

---

## Docs to align before first publish

Make sure these are truthful:

- Install command
- Package name
- CLI command names
- Repo targeting behavior
- Env loading behavior

**In this repo, re-check specifically:**

- `README.md`
- `docs/INSTALLATION.md`
- MCP config examples
- Any place implying `index --repo` exists — it currently does not

---

## Suggested order of operations

1. Decide the package name.
2. Revert the mistaken `0.2.2` bump and choose the actual first public version.
3. Build locally.
4. Smoke test the wheel in a clean install.
5. Publish to TestPyPI.
6. Install from TestPyPI in another environment and test `init`, `index`, `serve`.
7. Publish to PyPI.
8. Tag the release in git and record release notes.

---

## Biggest risks right now

- Package name confusion between **agent-memory-labs** and **agentic-codememory**
- Docs/examples drifting from actual CLI behavior, especially around `index`

---

## Next steps (optional)

A precise pre-release checklist for this repo only can be drafted from its current state on request.
