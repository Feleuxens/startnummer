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
uv sync --extra api --extra worker --extra ocr --extra face

cp .env.example .env
```

For API and frontend development without local inference, `uv sync --extra api`
is sufficient. Set the login password, session secret, and worker secret in `.env`.
Use separate random values of at least 32 characters for the two secrets. Then
migrate the database and build the frontend:

```sh
uv run --no-sync startnummer migrate

cd startnummer-web
npm ci
npm run build
cd ..
```

For frontend development, run `npm run dev` in `startnummer-web`. Astro proxies
`/api` to `http://127.0.0.1:8000`; set `STARTNUMMER_API_URL` to change the target.
`PUBLIC_API_URL` defaults to the same origin. A cross-origin deployment needs
its own authentication and proxy configuration. Set `STARTNUMMER_COOKIE_SECURE=1`
when serving through HTTPS.

The worker and API share the database, blob root, and worker secret. Gallery
credentials belong to the API; the launcher removes the gallery DSN and integration
encryption key from the worker environment. The worker's private face-session
service binds to `127.0.0.1:8766`. `--no-faces` disables face inference. `--once`
processes one job and exits, which also ends any face-review session.

For each album, the worker starts a separate inference process. That process
loads the models and keeps decoded photos, embeddings, and native inference
buffers. It exits before the job is marked complete and face review becomes
available. The worker receives analysis records plus temporary face boxes and
match groups; embeddings and decoded pixels never cross the process boundary.
The queue and review service stays running so other active reviews remain usable.

Models reload for each album, which adds startup time. Weights stay on disk and
may download on first use. Each inference process has a 512 MiB decoded-image
cache by default; use `--cache-mb` to change it or `--cache-mb 0` to disable it.
Cancellation and failed jobs stop the inference process before removing staging
files. On Linux, an inference child is also killed if its worker dies.
Process exit releases its CPU/GPU allocations; it does not overwrite physical
RAM or VRAM.

Finish any active face review before restarting the worker after an update.
An API restart preserves face data held by the running worker; a worker restart
clears it. If a session was created by an incompatible worker, the review screen
explains why propagation is unavailable. Individual face naming remains usable.
To get match groups, restart the updated worker and analyze a fresh batch. Keep
the existing batch to retain its review edits.

## Startup and status

On Linux, start the API and one worker with the launcher:

```sh
uv run --no-sync startnummer start --detach
uv run --no-sync startnummer status
```

Open <http://127.0.0.1:8000> and sign in with the credentials in `.env`. The API
serves the built frontend and photo endpoints. API documentation is at
`/api/docs`, with OpenAPI at `/api/openapi.json`.

The commands load `.env` automatically; existing environment variables take
precedence. Use `startnummer --env-file /path/to/config.env ...` for another file.
`start` stays in the foreground without `--detach`. The API listens on
`127.0.0.1:8000`; the worker's private service listens on `127.0.0.1:8766`.
`--port`, `--worker-port`, `--cache-mb`, and `--no-faces` configure a launch.
The worker receives neither the Chevereto DSN nor the integration encryption key.
Ports already in use produce an error; the launcher does not adopt or stop services
started elsewhere.

`status` reports API readiness, database and storage availability, worker state,
and the active face-session count. It exits with status 1 until the API is ready
and the worker is idle or busy. Model loading appears as a job phase; the queue
service does not load models. The public `/api/health/live` and `/api/health/ready` endpoints return health checks;
queue counts and settings require login.

The launcher restarts a failed process up to three times. An API restart leaves
the worker's face sessions intact; a worker restart loses them.
Detached output goes to `.startnummer/run/launcher.log`. Process state and the
log stay local; `--run-dir` selects another runtime directory. Before sending a
stop signal, the command checks the launcher's PID and Linux process start time:

```sh
uv run --no-sync startnummer stop
```

The worker finishes its current job before exiting. Stopping it ends temporary
face sessions. To switch from manually started services, finish active face review,
stop those processes, then run migrations and start the launcher. Tests use
separate processes and ports.

Workers can claim different album jobs concurrently, but face review must reach
the worker holding that batch's temporary session. The launcher runs one worker
until this routing is implemented. Each album is analyzed as one job.

To run the services separately during development, use two terminals:

```sh
uv run --no-sync --env-file .env startnummer-api
uv run --no-sync --env-file .env env -u STARTNUMMER_CHEVERETO_DSN -u STARTNUMMER_INTEGRATION_KEY startnummer-worker
```

## Administration

The configured photographer account has administrator access. Open
**Administration** to see service status and queue counts, or change the maximum
photo size, maximum batch size, and face-session lifetime. Import limits apply to
new imports. Lifetime changes apply to new face sessions; existing sessions keep
their expiry. The default is one hour. Finishing review, cancellation, deletion,
sign-out, and worker shutdown end sessions.

Settings are versioned in PostgreSQL and included in backups. Concurrent edits
require reloading the saved settings rather than overwriting another browser's
changes. Environment values provide defaults until settings are saved through the UI.
Startnummer's database connection, storage paths, and application secrets remain
in server configuration. Gallery connections support the two modes below.

## Chevereto connection

Open **Administration → Configured integrations** and expand **Chevereto** to inspect
or test the connection. Integrations start collapsed; their headers show the
configuration source and state. Collapsing keeps unsaved edits, with pending changes
or connection errors still indicated in the header. There are two configuration sources:

- If either `STARTNUMMER_CHEVERETO_URL` or `STARTNUMMER_CHEVERETO_DSN` is present,
  the whole connection is **Managed by environment**. Both values must be set.
  The page shows the connection fields but cannot edit them. Empty or incomplete
  environment values produce an error; they never fall back to a saved connection.
- If both variables are absent, configure the gallery URL, database host, port,
  database name, username, and password in Administration. Set a separate
  `STARTNUMMER_INTEGRATION_KEY` on the API server first. Generate a Fernet key with:

  ```sh
  uv run --no-sync python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
  ```

Remove or comment out both Chevereto variables to use Administration; setting
those variables to empty strings still selects environment management. The launcher
loads the key from `.env`. Keep it separate from the session and worker secrets.
The schema is created by one initial migration, `migrations/versions/initial.py`.
Its revision remains `0003` so complete pre-release development databases remain
compatible without a reset or restamp. Fresh databases get all tables in one step;
new production changes will use subsequent migrations.

**Test connection** checks database access and the supported Chevereto 4.5.9 schema
using reads only. It does not prove that the database user can update descriptions.
**Save connection** repeats this check, encrypts the connection with the server key,
and checks its revision before saving. New gallery operations use the saved values
without restarting the API. Leave the password field blank to keep the saved
password. Existing passwords are never returned to the browser.

Environment configuration takes precedence over a saved connection without deleting
it. Removing the environment configuration activates the saved connection again.
A missing or incorrect encryption key produces an error rather than using another
connection. Re-enter the connection with a new key if the original key is lost.

New imports record a gallery identity derived from Chevereto's installation salt.
The adapter verifies it before reading or writing a description. A database with
a different identity cannot replace the destination at a URL referenced by saved
photos. A database clone retaining that salt is treated as the same installation.
Older batches have no recorded identity: use **Confirm gallery for older batches…**
after checking that the configured gallery is their original destination. This
records the association without changing captions, approvals, or gallery descriptions.

Normal backups exclude saved connections and encryption keys. Gallery identity
bindings are retained, so restored batches keep their destination protection.
Configure the connection again after restoring. New archives use format 2;
format 1 archives remain readable.

## Backup and restore

Create and verify an archive of the configured account's saved records and photos:

```sh
uv run --no-sync startnummer backup /path/to/backups/startnummer.snbak
uv run --no-sync startnummer verify-backup /path/to/backups/startnummer.snbak
```

Use a new filename for each backup; existing archives are not replaced.

PostgreSQL backups can run while services are up. Imports, caption changes,
settings changes, and cleanup for the account wait while its referenced photo
bytes are copied. Worker lease heartbeats continue. Unreferenced files and
incomplete uploads are excluded. SQLite is supported for offline development and
test restores; use PostgreSQL for the running application.

The versioned archive contains database records, shared photo bytes, and SHA-256
checksums. Photo IDs, reviewed captions, approvals, jobs, publishing history, and
administrator settings are retained. Temporary face records, `.env`, credentials,
model weights, and Chevereto's database are excluded. Archive permissions are
owner-only. Keep the server configuration separately, including the original
username, which determines account ownership.

Restore requires an empty database and photo directory, supplied on the command
line. It verifies the archive, prepares the photo files, migrates the destination,
and inserts the records in a transaction. To create a recovered copy locally:

```sh
uv run --no-sync startnummer restore /path/to/backups/startnummer.snbak \
  --database-url sqlite:////tmp/startnummer-recovered.db \
  --blob-root /tmp/startnummer-recovered-photos
```

For PostgreSQL, create a dedicated empty database and pass its connection URL.
Do not run services against a restore destination until recovery completes. The
utility rejects existing records, unrelated tables, nonempty photo directories,
and archives belonging to a different account. For an interrupted restore, use
another empty destination; prepared photo files are retained if the commit outcome
is uncertain.

Queued and running jobs are restored as cancelled. Start analysis explicitly if
needed. Saved review work remains available without face data. Restoring
Startnummer does not restore or write gallery descriptions. Use **Check gallery
outcome** to reconcile any publishing operation whose result is uncertain.

If the `startnummer` command is not installed yet,
`uv run --no-sync python -m startnummer.app.manage ...` runs the same commands.

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
   After selecting a face or subject, use **Search roster athletes** to filter
   **Assign roster athlete** by name, bib, or club. Search terms can be combined;
   each result shows all three fields. Choose an athlete and save the correction.
   Searching alone does not change the assignment.
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

For a sequence from the same event, choose **Select photos**. Check individual
photos, Shift-click to extend a selection, or use **From photo**, **Through photo**,
and **Select range**. Ranges follow album order within the current filter;
changing the filter clears the selection. The **Undetermined discipline** filter
shows analyzed photos without an assigned discipline. Photos marked **No event**
are excluded.
Choose **Assign discipline…**, select a discipline, and preview the captions before
confirming. Roster events appear as suggestions above the full discipline list;
any listed discipline can be assigned even if absent from the roster. Manually
edited captions are kept. The preview identifies existing manual disciplines
that will be replaced, and changed photos lose approval. If any selected photo
changed since the preview, the whole assignment is rejected; reload and preview again.

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
- One worker processes album jobs on the app host. Each album runs in a spawned
  inference process, which exits before review results are published. The API
  and queue service do not load ML runtimes. Leases and fencing tokens prevent
  stale workers from saving results. Run migrations before starting an updated
  installation.
- With a roster, only exact roster bibs and manual corrections constrain face
  groups or donate bibs to other photos. Unsupported machine reads remain review
  evidence. The face-similarity threshold is unchanged.
- Face embeddings, decoded photos, and retained model buffers are confined to the
  inference process. Face boxes, match groups, and undo records stay
  in queue-worker memory during review and expire after one hour by
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
exports, roster formats, and cross-album person erasure are outside the current
implementation.

## Frontend structure

`Workspace.tsx` handles sign-in and screen navigation. `AppShell.tsx` renders the
sidebar and page header. Import, saved albums, and administration are separate
screens. Album review lives in `startnummer-web/src/features/review/`:

- `BatchReview.tsx` coordinates the active album, editor, and confirmation dialogs.
- `PhotoEditor.tsx` owns the unsaved caption and correction draft. Its photo ID and
  revision key reset the draft when a different saved revision is opened.
- `ReviewHeader`, `ReviewControls`, `PhotoQueue`, and `PhotoViewer` render the
  analysis controls, filters, selections, and selected photo.
- `PublishingHistory.tsx` handles inspection and conditional restore of past writes.
- `api.ts` names the review requests and uses the generated HTTP client.

`useBatch` refreshes the saved batch and prevents older responses from replacing a
newer refresh. `useFaceSession` holds temporary face selectors and propagation
previews in memory and clears them on expiry. Review stays mounted while another
screen is open so polling and expiry continue; reopening an album starts fresh
selection state. Face data is not retained in the screen-opening state or browser
storage. Shared hooks handle request feedback and the unsaved-changes guard.

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
STARTNUMMER_TEST_DATABASE_URL='postgresql+psycopg://startnummer:startnummer@127.0.0.1:5432/startnummer' \
STARTNUMMER_TEST_MYSQL_DSN='mysql://root:password@127.0.0.1:3306/startnummer_test_adapter' \
uv run --no-sync pytest tests/test_database_integration.py tests/test_backup_postgres.py
```

Chevereto 4.5.9 has been checked on the local test instance by applying a
description, checking the rendered image page, and restoring the original.
Database updates were visible without cache invalidation. Repeat this check
when changing the adapter or supported version; SQL success alone does not
confirm what the gallery displays. This integration check does not measure
inference accuracy.

Automated recovery tests include a synthetic 93-photo batch with a 262-entry
roster; this does not verify real model accuracy on the representative photos.
Inference-lifetime tests use synthetic adapters in real subprocesses, including
retained image buffers, cancellation, abnormal exit, and Linux parent-death cleanup.
They require no GPU or model downloads.
