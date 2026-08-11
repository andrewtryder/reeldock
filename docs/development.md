# Development Guide

This guide is for developers looking to modify or contribute to `reeldock`.

## 1. Local Environment Setup

To run the application locally without Docker, install [uv](https://docs.astral.sh/uv/getting-started/installation/) and sync the project environment:

```bash
uv sync --dev
```

Run project tools through uv:

```bash
uv run pytest
uv run ruff check .
```

Run the same checks as CI before opening a PR:

```bash
uv sync --locked --dev
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen mypy app worker
uv run --frozen coverage run -m pytest
uv run --frozen coverage report
```

### Rebuilding UI CSS

The Web UI serves a compiled Tailwind stylesheet (`app/static/tailwind.css`) — there is no runtime CDN. After changing utility classes in `app/templates/`, regenerate:

```bash
npm install --prefix ui
npm run build:css --prefix ui
```

Commit the updated `app/static/tailwind.css` with your template changes.

### Updating dependencies

When adding or changing dependencies:

1. Edit `[project.dependencies]` and/or `[dependency-groups].dev` in `pyproject.toml`
2. Run `uv lock`
3. Run `uv sync --dev`
4. Run the CI-equivalent checks above
5. Commit `pyproject.toml` and `uv.lock`

---

## 2. Infrastructure Requirements

The application requires a running Redis instance to manage the job queue. You can run Redis locally using Docker:

```bash
docker run -d -p 6379:6379 redis:8.10-alpine
```

---

## 3. Starting the Application Services

You need to start two processes in separate terminals:

### A. Start the FastAPI Web Server
Configure the local environment variables and start the server using `uvicorn`:

```bash
# Set local environment variables
export REDIS_URL=redis://localhost:6379/0
export DATABASE_URL=sqlite+aiosqlite:///./app.db
export OUTPUT_ROOT=/tmp/test-podcasts
export WORK_DIR=/tmp/reeldock-work
export DRY_RUN=true  # Set to true to avoid running actual yt-dlp/ffmpeg processes

# Start uvicorn server
uv run uvicorn app.main:app --reload --port 8080
```

The web interface will be accessible at `http://localhost:8080`.

### B. Start the Background RQ Worker
In a new terminal window, start the worker:

```bash
uv run rq worker reeldock --url redis://localhost:6379/0
```

---

## 4. Running Tests

The repository includes a comprehensive test suite using `pytest`.

```bash
uv run pytest
```

Coverage is measured over `app/` and `worker/` (`fail_under = 80`, branch coverage). For CI parity:

```bash
uv run --frozen coverage run -m pytest
uv run --frozen coverage report
```

Browser extension unit tests live under `browser-extension/test/`. The CI gate requires 80% line coverage of `browser-extension/src`:

```bash
npm --prefix browser-extension test
npm --prefix browser-extension run test:coverage
```

---

## 5. Linting and Formatting

The codebase uses `ruff` to enforce code quality and styling consistency.

```bash
uv run ruff check .
uv run ruff format --check .

# Auto-format codebase
uv run ruff format .
```

Pre-commit hooks use the same Ruff version from `uv.lock` via `uv run --frozen`.

---

## 6. Database schema

Schema is defined by SQLAlchemy models in `app/models.py` and versioned with **Alembic**.

On startup, `init_db()` runs `alembic upgrade head`. Pre-baseline SQLite databases are detected and stamped first:

- tables present with no `alembic_version` (unversioned legacy)
- databases carrying a known retired ReelDock revision ID

Those DBs are reconciled to the **frozen 0001** schema in `app/baseline_schema.py` (not live ORM models), then stamped at `0001_baseline`. Unknown revision IDs fail loudly. Later schema changes advance only through Alembic revisions (`0002`, …). Do not edit `app/baseline_schema.py` to match future models.

### Changing the schema

1. Edit models in `app/models.py`
2. Generate a revision: `uv run alembic revision --autogenerate -m "describe change"`
3. Review the generated script under `alembic/versions/` (do not modify `app/baseline_schema.py`)
4. Apply locally: `uv run alembic upgrade head` (also runs automatically on app start)
5. Commit the revision with your model change

### Worker-only startup

The RQ worker does not initialize the schema. In Docker Compose the `worker` service waits for the `app` service to become healthy (`/ready`), so Alembic migrations finish before the worker starts. Both share the same `./data` volume. For worker-only local setups, start the app once before the worker.

---

## 7. Release-smoke (Compose real conversion gate)

Issue [#118](https://github.com/andrewtryder/reeldock/issues/118): run the **shipping** Docker image with a real worker + ffmpeg path and assert a valid `.m4b` **without live YouTube**.

Fixtures live in `tests/fixtures/release_smoke/`. When `RELEASE_SMOKE_FIXTURE=true`, the worker stages canned audio instead of calling yt-dlp, then runs the normal remux/verify/commit path. Reserved watch IDs:

- `rdSmoke01001` — happy path
- `rdSmokeFail1` — fail once (`attempts == 1`), succeed on retry
- `rdSmokeSlow1` — short sleep after staging so Cancel can win

Local run (Docker + host `ffprobe` required):

```bash
./scripts/compose-release-smoke.sh
```

Playwright golden path (home → preview → queue → Done):

```bash
cd e2e && npm ci && npx playwright install chromium
cd .. && ./scripts/compose-playwright-smoke.sh
```

Browser extension E2E (unpacked Chrome, mocked YouTube, headed under `xvfb-run` in CI):

```bash
./scripts/compose-extension-e2e.sh
```

See [e2e/README.md](../e2e/README.md). Optional-host permission dialogs are not covered in the browser suite.

CI workflow: `.github/workflows/release-smoke.yml` (workflow_dispatch, `v*` tags, and PRs that touch pipeline/Docker/e2e/extension paths). Unit `ci.yml` stays fast and separate.

Do **not** enable `RELEASE_SMOKE_FIXTURE` in production.
