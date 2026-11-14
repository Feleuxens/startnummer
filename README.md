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
weights on first use. The worker's decoded-image cache is limited to 512 MiB by
default; use `--cache-mb` to change the limit or `--cache-mb 0` to disable it.

Finish any active face review before restarting the worker after an update.
An API restart preserves face data held by the running worker; a worker restart
clears it. If a session was created by an incompatible worker, the review screen
explains why propagation is unavailable. Individual face naming remains usable.
To get match groups, restart the updated worker and analyze a fresh batch. Keep
the existing batch to retain its review edits.

## Reviewing a batch

1. Choose **New batch**. Import photos from a configured Chevereto album URL or
   upload JPEG, PNG, or WebP files. Import the roster independently from a
   supported URL or uploaded Competitoroverview HTML.
2. Check the saved photo count and roster sample. Supply a meet name if wanted
   in captions; the parser currently leaves it blank.
3. Start analysis. The worker processes the saved batch as a whole, matching
   athletes and propagating bibs through face matches before resolving disciplines.
   Progress and failed photos appear in the review screen.
   **Cancel analysis** stops the job from saving further results and keeps saved
   review work. An active model call may finish before the worker stops processing.
4. Review the existing description, suggested caption, and evidence. Captions,
   bibs, names, clubs, and disciplines are editable. **No event** explicitly omits
   a discipline. A detected face can be named individually, from the roster or
   with a name absent from it.
   If a person was not detected, use **Add person from roster**, search by name,
   bib, or club, and choose **Add to this photo**. This also works before analysis.
   The roster assignment generates a caption suggestion without creating a bib
   read or face detection. **Remove added person** reverses an accidental addition.
   After saving a name, select that subject and choose **Find matching faces…**.
   Check the candidate photos, exclude wrong matches, and confirm the selection.
   Manual identities and bib corrections are protected. Edited captions and manual
   disciplines are kept; changed photos require approval again.
   Matches that already have the selected name are labeled **Already named**.
   A tentative roster guess can be replaced after confirming the warning. A
   different confirmed name requires individual review. **Review this photo**
   opens a match that cannot be changed through propagation.
   Strong machine bib reads absent from the saved roster appear as warnings.
   Confirm the selected faces and those reads before assigning names; the reads
   remain in the evidence and the photos still need review. Conflicting roster
   bibs and manual corrections cannot be overridden by this confirmation.
   **Undo last name assignment** restores the last propagation during the active
   session. It refuses to overwrite later edits and never restores approval.
   Its undo data expires with the face session; it does not restore gallery changes.
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

For interrupted or failed publishing, **Check gallery outcome** reads the live
description without writing. If a gallery description changed, **Load live
description for review** updates the comparison value and removes approval and
replacement consent. Review it, explicitly choose replacement, and approve again
before applying. Filters include failed analysis, publishing issues, and published
photos; publishing filters use the latest operation for each photo.

Previous/next controls follow the current filter and stop at either end. Leaving
unsaved edits requires confirmation. Uploaded photos can be reviewed without a
gallery destination; they cannot be published to an existing image automatically.

Caption saves keep face selection available during the active session.
**Save review and finish face session** saves the review and removes the extracted
face data. Saved albums can be reopened later with photos, names, and captions.
Signing out also cancels active analysis and clears temporary face data.

## Data and process boundaries

- Photo UUIDs identify individual entries. Identical image bytes can share a blob
  within an owner's storage, while retaining separate gallery mappings and reviews.
- PostgreSQL stores batches, photo order, job leases, and publication history.
  Rosters and analysis results use versioned Pydantic JSON documents. Temporary
  inference paths are removed before saving.
- One worker processes album jobs on the app host. Leases and fencing tokens
  prevent stale workers from saving results. The API process does not load ML
  runtimes. Run migrations before starting an updated installation.
- With a roster, only exact roster bibs and manual corrections constrain face
  groups or donate bibs to other photos. Unsupported machine reads remain review
  evidence. The face-similarity threshold is unchanged.
- Face embeddings are released after analysis. Face boxes, match groups, and undo
  records stay in worker memory during review and expire after one hour by
  default. Finishing review, cancelling analysis, deleting a batch, signing out,
  or stopping the worker clears them. They are never saved to the database or
  photo storage. Saved names and assignment notes survive the face session.
- A confident propagated bib can replace a tentative roster guess during
  analysis. Manual identities and confirmed matches are preserved. Name-only OCR
  matches remain suggestions; printed text can resemble a roster surname.
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
exports, roster formats, and cross-album person erasure are
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
Run Python and browser checks in sequence: the frontend build replaces `dist/`,
which the API test fixtures may read when they start.

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

The full-album photographer acceptance checklist and remaining backlog decisions
are in [docs/acceptance.md](docs/acceptance.md). Automated recovery tests include a
synthetic 93-photo batch with a 262-entry roster; this does not verify real model
accuracy on the representative photos.
