# Startnummer

Startnummer generates sports photo captions from bib reads, face matches within
an album, and a competition roster. Import photos, analyze the batch, review the
captions, and apply approved descriptions to existing Chevereto images.

The gallery adapter supports **Chevereto 4.5.9** with `chv_` tables. Startnummer
stores its own batches and review state in PostgreSQL, separately from Chevereto.

## Local setup

Requires Python 3.12, uv, Node.js compatible with Astro 7, and PostgreSQL.
The local test services in `docker-compose.yml` expose PostgreSQL on port 5432,
MariaDB on 3306, and Chevereto at <http://localhost:8115>.

```sh
# API and review UI
uv sync --extra api

# Include inference when running analysis
uv sync --extra api --extra worker --extra ocr --extra face

cp .env.example .env
```

Set the login password, session secret, and worker secret in `.env`. Use separate
random values of at least 32 characters for the two secrets. Then migrate the
database and build the frontend:

```sh
set -a
source .env
set +a
uv run --no-sync alembic upgrade head

cd startnummer-web
npm ci
npm run build
cd ..
```

Start the API and worker in separate terminals:

```sh
uv run --no-sync --env-file .env startnummer-api
uv run --no-sync --env-file .env env -u STARTNUMMER_CHEVERETO_DSN startnummer-worker
```

Open <http://127.0.0.1:8000> and sign in with the credentials in `.env`. The API
serves the built frontend and photo endpoints. API documentation is available
at `/api/docs`, with OpenAPI at `/api/openapi.json`.

For frontend development, run `npm run dev` in `startnummer-web`. Astro proxies
`/api` to `http://127.0.0.1:8000`; set `STARTNUMMER_API_URL` to change the target.
`PUBLIC_API_URL` defaults to the same origin. A cross-origin deployment needs
its own authentication and proxy configuration. Set `STARTNUMMER_COOKIE_SECURE=1`
when serving through HTTPS.

The worker and API share the database, blob root, and worker secret. Gallery
credentials belong to the API; the worker command removes the gallery DSN from
its environment. The worker's private face-session service binds to
`127.0.0.1:8766`. `--no-faces` disables face inference. `--once` processes one job
and exits, which also ends any face-review session. Model adapters may download
weights on first use.

## Reviewing a batch

1. Choose **New batch**. Import photos from a configured Chevereto album URL or
   upload JPEG, PNG, or WebP files. Import the roster independently from a
   supported URL or uploaded Competitoroverview HTML.
2. Check the saved photo count and roster sample. Supply a meet name if wanted
   in captions; the parser currently leaves it blank.
3. Start analysis. The worker processes the saved batch as a whole, matching
   athletes and propagating bibs through face matches before resolving disciplines.
   Progress and failed photos appear in the review screen.
4. Review the existing description, suggested caption, and evidence. Captions,
   bibs, names, clubs, and disciplines are editable. **No event** explicitly omits
   a discipline. A detected face can be named individually, from the roster or
   with a name absent from it.
5. **Approve this photo** and the evidence checkbox affect the open photo.
   **Approve all eligible** lists the affected captions for confirmation, including
   photos hidden by the filter. Blank captions and unresolved cases are excluded.
   Replacing an existing gallery description requires an explicit choice.
   **Unapprove this photo** keeps the caption and evidence. Editing or rerunning
   analysis invalidates approval.
6. Use **Preview Apply** to inspect the before/after values, then **Apply to
   Chevereto** to write approved descriptions. Changed gallery descriptions are
   reported as conflicts. Publication history records individual outcomes and
   supports conditional restore.

Previous/next controls follow the current filter and stop at either end. Leaving
unsaved edits requires confirmation. Uploaded photos can be reviewed without a
gallery destination; they cannot be published to an existing image automatically.

Caption saves keep face selection available during the active session.
**Save review and finish face session** saves the review and removes the extracted
face data. Saved albums can be reopened later with photos, names, and captions.

## Data and process boundaries

- Photo UUIDs identify individual entries. Identical image bytes can share a blob
  within an owner's storage, while retaining separate gallery mappings and reviews.
- PostgreSQL stores batches, photo order, job leases, and publication history.
  Rosters and analysis results use versioned Pydantic JSON documents. Temporary
  inference paths are removed before saving.
- One worker processes album jobs on the app host. Leases and fencing tokens
  prevent stale workers from saving results. The API process does not load ML
  runtimes. Run migrations before starting an updated installation.
- Face embeddings are released after analysis. Face geometry stays in worker RAM
  for review and expires after one hour by default. Finishing review, deleting a
  batch, logging out, or stopping the worker also removes it. Neither geometry
  nor embeddings are saved to the database or photo storage.
- Reruns preserve manual captions and identity/discipline decisions. Photos that
  retain manual subject records receive no fresh face selectors, because new
  detections cannot safely be mapped to the old subject indexes.
- The single configured photographer signs in through a signed HttpOnly,
  SameSite cookie. Requests use session ownership, private `no-store` responses,
  and a required header for writes.
- Publishing records the intended change before writing to Chevereto. Retries
  reuse that operation. Conditional SQL compares the exact previous description,
  including `NULL`, regardless of MariaDB text collation. Restore checks that the
  live description still equals the value Startnummer wrote.
- Deleting a batch removes Startnummer data. Shared blobs remain until their last
  reference is removed; failed file cleanup is queued for retry.

Chevereto imports support local datefolder, direct, and path image storage.
External and legacy storage modes produce import errors. Additional galleries,
exports, roster formats, name propagation, and cross-album person erasure are
outside the current implementation.

## Development checks

The default tests use synthetic HTML/photos and fake inference and gallery
adapters. They require no models, GPU, or gallery credentials.

```sh
uv run --no-sync pytest
uv run --no-sync ruff check startnummer tests migrations scripts
uv run --no-sync ruff format --check startnummer tests migrations scripts
uv run --no-sync lint-imports --no-cache

cd startnummer-web
npm run format:check
npm test
```

Use `ruff format` and `npm run format` to format source files. Generated API files
are excluded from Prettier; `npm run generate` regenerates them from the Python
contracts. Frontend builds generate the client and type-check before bundling.

Browser tests build the frontend and start a disposable SQLite fixture app.
Set `CHROMIUM_PATH` if Chromium is not at `/usr/bin/chromium`.

SQL integration tests are opt-in. PostgreSQL tests create and drop a random
schema. The MariaDB DSN must name a dedicated `startnummer_test_*` database:

```sh
STARTNUMMER_TEST_DATABASE_URL="$STARTNUMMER_DATABASE_URL" \
STARTNUMMER_TEST_MYSQL_DSN='mysql://root:password@127.0.0.1:3306/startnummer_test_adapter' \
uv run --no-sync pytest tests/test_database_integration.py
```

Chevereto 4.5.9 has been checked on the local test instance by applying a
description, checking the rendered image page, and restoring the original.
Database updates were visible without cache invalidation. Repeat this check
when changing the adapter or supported version; SQL success alone does not
confirm what the gallery displays. This integration check does not measure
inference accuracy.
