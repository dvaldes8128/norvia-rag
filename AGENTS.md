# AGENTS.md — working conventions for this repo

## Testing & CI
- **Do NOT run tests locally.** Rely on GitHub Actions CI to run linters and the test
  suite. Keep CI green: push changes and let the pipeline validate them.
- After any push, check the CI run status (`gh run list` / `gh run watch`) and fix
  failures promptly so `main` stays green.
- When changing lint/test config, update `.github/workflows/ci.yml` accordingly so CI
  stays the single source of truth for verification.

## Project docs
- Requirements live in `SPEC.md`; decisions and trade-offs in `DECISIONS.md`.
- Language: all code, comments and in-repo docs in English.
