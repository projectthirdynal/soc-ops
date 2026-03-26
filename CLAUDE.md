# SOC Data Processor

## Architecture
- Desktop app: FastAPI + DuckDB + pywebview (native window), bundled with PyInstaller
- Backend runs on localhost random port, pywebview connects to it
- Entry point: `main.py` → `app/api/__init__.py:create_app()`
- UI: vanilla HTML/JS/CSS in `app/ui/`
- Version defined in `app/core/version.py` — bump before each release

## Build & Deploy
- `app.spec` — PyInstaller config (onedir, `console=False`)
- `installer.iss` — Inno Setup Windows installer
- `build_installer.bat` — PyInstaller + Inno Setup one-click build
- `publish_github.bat` — Create GitHub Release with `gh` CLI
- OTA updates via GitHub Releases API (`github:projectthirdynal/soc-ops`)

## Key Patterns
- All file output must be XLSX (openpyxl), not CSV
- Long operations use SSE (Server-Sent Events) for progress — see `/api/split/file/progress`
- SQL queries must use parameterized queries — no f-strings with user input
- HTML output must use `escapeHtml()` — XSS prevention
- Column names validated against `INFORMATION_SCHEMA` before use in SQL
- Threading locks via `app/api/ops_lock.py` for concurrent operation safety

## Gotchas
- PyInstaller `console=False`: `sys.stdout`/`sys.stderr` are `None` — guard all logging/print
- DuckDB VALUES lists don't have `rowid` — use CTEs with named key columns
- Static files path differs in PyInstaller bundle — check `sys._MEIPASS` fallback in `app/api/__init__.py`
- GitHub API returns 404 when repo has no releases — handle gracefully in updater

## Testing
- No test suite yet — test manually by running `python main.py`
- Build testing requires Windows (PyInstaller + Inno Setup)
