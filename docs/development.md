# Develop Startnummer

Use this guide to run the source locally and check a change. For a Linux server,
use the [Docker quick start](docker.md); for Apple acceleration, use
[native installation](devices.md#install-on-apple-silicon).

## Set up a checkout

You need Python 3.12, uv, Node.js 24, and PostgreSQL. Docker Compose can provide
the local test databases and Chevereto:

```sh
git clone https://github.com/Feleuxens/startnummer.git
cd startnummer
uv sync --extra api
cp .env.example .env
docker compose -f compose.dev.yaml -p startnummer-dev up -d
```

This test stack exposes PostgreSQL on port 5432, MariaDB on 3306, and Chevereto
at <http://localhost:8115>. Its development credentials are in `compose.dev.yaml`.
Keep its project name distinct from a production deployment on the same host.

`api` is enough for API/frontend work and the default tests. To run real inference,
install one [device profile](devices.md) alongside it, such as
`uv sync --extra api --extra cpu`.

Set random session/worker secrets in `.env` using the
[native configuration steps](devices.md#2-configure-the-app). Set the database URL
and photo root for your local installation. Then migrate and build:

```sh
uv run --no-sync startnummer migrate
cd startnummer-web
npm ci
npm run build
cd ..
```

Start the app with `uv run --no-sync startnummer start --detach`. An inference
profile is needed when analyzing albums. Use `uv run --no-sync startnummer
setup-code` to create a new installation's administrator. See
[Accounts](accounts.md#use-an-environment-configured-account) when keeping a
configured login, or [Backups](backups.md) when recovering saved work.

## Work on the frontend

In `startnummer-web`, run `npm run dev`. Astro proxies `/api` to
`http://127.0.0.1:8000`; set `STARTNUMMER_API_URL` to use another API. Keep the
browser and API on the same public origin. `PUBLIC_API_URL` defaults to that origin.

Python HTTP contracts generate `openapi.json` and `src/api/schema.d.ts`:

```sh
cd startnummer-web
npm run generate
npm run check
```

Edit `startnummer/app/contracts.py` and regenerate the client instead of editing
the generated files. `src/api/types.ts` contains shared aliases.

Use [Workspace design](../startnummer-web/DESIGN.md) for interface changes and
[Architecture](architecture.md) for module boundaries and state ownership.

## Run the default checks

The default tests use synthetic photos/HTML and fake inference/gallery adapters.
They need no model downloads, GPU, private athlete data, or live gallery credentials.

From the repository root:

```sh
uv run --no-sync pytest
uv run --no-sync ruff check startnummer tests migrations scripts
uv run --no-sync ruff format --check startnummer tests migrations scripts
uv run --no-sync lint-imports --no-cache
```

Then check the frontend:

```sh
cd startnummer-web
npm run format:check
npm test
```

`npm test` regenerates contracts, checks TypeScript, builds, and runs Playwright
against disposable SQLite apps. Set `CHROMIUM_PATH` if Chromium is not installed
at `/usr/bin/chromium`. Run Python tests and frontend builds/browser tests in
sequence: builds replace `dist/`, which API fixtures can be serving.

Use `ruff format` and `npm run format` to format code. Generated API files are
excluded from Prettier. Keep fixtures independent of a pre-existing frontend build
so checks work in a clean checkout.

## Test PostgreSQL and MariaDB changes

SQL integration checks are opt-in. PostgreSQL fixtures create and drop random
schemas. MariaDB checks require a dedicated database whose name starts with
`startnummer_test_`.

```sh
STARTNUMMER_TEST_DATABASE_URL='postgresql+psycopg://startnummer:startnummer@127.0.0.1:5432/startnummer' \
STARTNUMMER_TEST_MYSQL_DSN='mysql://root:password@127.0.0.1:3306/startnummer_test_adapter' \
uv run --no-sync pytest tests/test_database_integration.py tests/test_accounts_postgres.py tests/test_backup_postgres.py
```

Use test credentials and databases only. For a Chevereto adapter change, also
apply one test description, check the rendered photo page, and restore it.
Successful SQL alone does not confirm what the gallery displays. Local 4.5.9
checks have shown writes without additional cache invalidation.

## Test the Docker deployment

```sh
STARTNUMMER_TEST_DOCKER=1 uv run --no-sync pytest tests/test_docker.py -v
```

This builds CPU images and creates a randomly named disposable Compose project
with its own database, ports, and volumes. It checks setup, import, a real queue
and subprocess with synthetic inference, review persistence, face cleanup,
restart, and backup/restore. It removes its own resources afterward.

The synthetic adapter belongs only to the test fixture; it is not a production
inference option. Use [backend checks](devices.md#check-a-runtime) and a
representative album to evaluate real models on the target hardware.

## Work with experiments

`scripts/try_*.py` are experiments, not production entry points or tests.
`analysis.json` is sample output, not expected truth. Keep private photos, athlete
identities, generated face previews, model weights, and runtime files out of
fixtures and commits.
