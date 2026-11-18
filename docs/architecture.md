# Architecture

Startnummer keeps imported inputs and reviewed work independently of Chevereto.
The app owns batches, jobs, and accounts; the gallery adapter updates descriptions
on explicitly mapped remote images.

## Follow the dependency boundaries

Dependencies point inward: `app` → `adapters` → `core`. Import-linter checks this.

| Area                                              | Responsibility                                                            |
| ------------------------------------------------- | ------------------------------------------------------------------------- |
| `core/pipeline.py`                                | Synchronous album analysis with injected detector, OCR, and face adapters |
| `core/batch.py` and analysis models               | Photo identity, revisions, approvals, jobs, and publication records       |
| `app/api.py`, `account_routes.py`, `contracts.py` | HTTP boundary, authentication dependencies, and generated contracts       |
| `app/services.py`                                 | Import, review, and publication use cases                                 |
| `adapters/db/` and `adapters/blob/`               | Owner-scoped records and original photo bytes                             |
| `app/worker.py` and `app/inference.py`            | Durable queue, disposable inference, and temporary review sessions        |
| `app/integrations.py` and `adapters/chevereto.py` | Connection snapshots and Chevereto SQL                                    |
| `startnummer-web/`                                | Astro/React workspace and review UI                                       |

Database sessions are synchronous and transactions belong to a use case. FastAPI
runs database handlers in its threadpool. API imports and startup do not load
ML runtimes. Keep provider-specific SQL and native runtime details in adapters.

The older `AlbumStore`, `MetadataStore`, and `Exporter` ports are experimental
scaffolding, not application persistence. The old `(owner_id, content_hash)` key
cannot identify an individual photo's review state.

## Keep saved inputs and review decisions separate

Import saves a fixed photo manifest, normalized roster, stable photo UUIDs, and
readable byte references before queueing analysis. Retries use these saved inputs.
Fetching and uploading roster HTML share the same parser.
Both layouts use the same name-order rules. New rosters retain the source name,
chosen name order, and uncertain automatic decisions beside their athlete entries.
A preview digest binds per-entry name corrections to the parsed roster and its
order; a changed URL cannot apply an index correction to a different athlete.
Manual roster assignment uses a saved roster index, including entries without
bibs. Legacy bib-based correction requests remain supported. Existing roster
documents load without name-parsing metadata and are not reparsed on reopening.

Imports without a roster save an empty entry list. The worker passes no roster
to inference, preserving OCR evidence and face grouping without roster matching.
Manual naming and confirmed face propagation use the same review flow.

Identical photo bytes can share storage within an account, while each photo keeps
its own identity, destination, caption, and approval. Cleanup deletes bytes only
after their last retained reference is released. Failed deletion is retried.

Analysis recommendations, reviewed captions/approvals, and publication outcomes
are separate records. Confidence is not approval. Reruns preserve manual captions,
identity and discipline decisions, explicit bib removal, and caption exclusions.
Retained subject layouts do not receive fresh face selectors because detection
indexes can change.

## Face-data lifetime

Embeddings, extracted face geometry, keypoints, match-group lookup data, and undo
records must not enter databases, files, logs, browser storage, backups, or an
identity gallery. Durable assigned names, roster decisions, and captions are
separate review data. Imported original photos are retained inputs.

For each album, the worker starts a fresh inference process. ML imports, model
buffers, embeddings, and decoded photos stay in that child. A pipe returns
analysis records, progress, and typed review boxes/groups, not embeddings or
decoded pixels. The worker waits for child exit and cache cleanup before
publishing completed results.

Cancellation, lease loss, and crashes stop and join inference before removing
staged inputs. Linux uses a parent-death signal. On macOS, a separate model-free
watchdog observes a pipe owned by the queue worker and kills orphaned inference.
It runs independently because native inference can hold the Python GIL.
Injected synthetic adapters use `InlineAnalyzer`, which clears caches in `finally`.
The image cache's generation counter prevents a decode from repopulating a cache
that was cleared while decoding.

After inference, only temporary review boxes, match groups, and undo remain in
worker memory. Sessions own and return copies. Finishing, cancellation, deletion,
expiry, sign-out, password change, session revocation, and shutdown discard them.
Ordinary caption saves retain the session. Both wall and monotonic deadlines
prevent laptop suspend from extending its original lifetime.

A compatible API restart can retain a running worker's session. A worker restart
or `--once` exit loses every session it holds. API responses identify protocol
compatibility and propagation availability; inspect those before changing match
thresholds. Process exit releases allocations but does not promise physical
RAM/VRAM zeroization. See [Operations](operations.md#check-persistent-storage)
for tmpfs and swap configuration.

## Resolve identities conservatively

Caption name overrides are private per-account display rules in the existing
settings document. They replace a full name only while building the caption;
roster entries and matched athlete identities retain their original values.
Runtime settings reads ignore caption preferences, and updates preserve each
other's fields under the shared settings revision. Backups validate and retain
both kinds of settings without including credentials or face records.

Analysis takes a snapshot of the owner's rules when the worker starts the job.
Review regeneration uses current rules. Discipline and face-propagation previews
carry the settings revision so applying a stale preview cannot change its caption
silently. Saving rules does not rewrite saved photos. An explicit suggestion
refresh preserves manual text, revokes approval only when the suggestion changes,
and leaves the temporary face session intact.

With a roster, exact roster bibs and manual corrections constrain face groups and
donate bibs to other photos. Unsupported machine reads remain uncertain evidence,
even with high OCR confidence. They must not split a valid face group or spread an identity.
Without a roster, confident bib reads can constrain face groups and propagate;
conflicting reads still require review. Names are assigned manually.
A confident propagated bib can replace a tentative name; confirmed/manual
identities and genuine roster conflicts remain protected.

Review acknowledgements confirm warnings and tentative replacements. They do not
bypass manual decisions, revisions, or face-session checks. Propagation undo is
session-only, refuses later edits, and never restores approval.

## Protect queue completion

One queue worker processes album-wide jobs. PostgreSQL leases and fencing tokens
prevent expired claims from saving results. Heartbeats continue during online
backups. Worker cancellation and shutdown interrupt staging/inference and discard
review sessions.

The queue can claim separate albums concurrently, but multiple workers are not
exposed as an operational setting: review requests need routing to the worker
that owns each batch's temporary session first.

## Publish conditionally

Gallery imports retain installation identity, remote image ID, and the exact
imported description. Uploads have no inferred destination. Each operation takes
a connection snapshot; worker processes receive no gallery credentials.

Publishing records intent before parameterized SQL updates an existing image.
The update compares the exact expected live value, including `NULL`, independently
of MariaDB text collation. Each photo records applied, unchanged, conflict, or
failure results and before/after values. Retries reuse the publication record.
Restore also compares the live value with what Startnummer wrote.

Gallery identity is derived from Chevereto's installation salt. A clone retaining
the salt shares identity; older unbound albums need explicit confirmation. See
[Chevereto](chevereto.md) for configuration and [Review](review.md#5-apply-descriptions-to-chevereto)
for conflict recovery.

## Accounts and secrets

Authentication supplies the owner UUID for every domain read/write; callers
cannot select another owner. Administrator access does not grant access to other
users' batches. Passwords are Argon2id hashes. Random session tokens are held in
HttpOnly, SameSite=Strict cookies; the database stores keyed digests and expiry.
Every authenticated request checks its session record.

First-admin creation, invitation claims, and registration-policy changes are
serialized in database transactions. Setup codes derive from the session secret
and are available only through the CLI while unclaimed. Invitations use random,
expiring single-use tokens; their URL fragments stay out of HTTP paths and proxy
access logs. Their database records contain keyed digests, not usable links.

Changing the session secret invalidates sessions and unused invitations, resets
the sign-in keys, and changes an unclaimed setup code. Sign-in limits share
short-lived, keyed source and normalized username counters in PostgreSQL. A short
transaction reserves a slot before Argon2 runs. Success refunds the source slot
and clears the username's failures. Password verification holds no database lock.
Expired counters are pruned during sign-in and are excluded from backups.
Setup, registration, and password changes use separate process-local limits.
The API uses the client address resolved by Uvicorn's trusted proxy settings.

Gallery credentials saved through Administration are encrypted with a separate
Fernet key. Environment connections take precedence when either connection
variable exists, including empty values; broken configuration cannot select a
fallback silently. See [Accounts](accounts.md) and [Chevereto](chevereto.md).

## Database and recovery

Startnummer uses PostgreSQL; Chevereto uses its separate MariaDB database.
SQLite is for disposable tests and offline development. Revision `1` is the
first-release baseline. Later migrations upgrade existing installations in place.
Earlier pre-release revision IDs require a fresh database.

Application archive format 3 retains one account's username, owner UUID, saved
records, photo bytes, and checksums. Formats 1 and 2 remain readable. Authentication
state, integrations, keys, and temporary face data are excluded. Restore creates
a pending account for setup into an empty destination; it cannot merge users.
Prepared bytes remain after an uncertain commit to protect possibly committed
references. See [Backups](backups.md) for the recovery procedure.

## Frontend state ownership

`Workspace` owns authentication and navigation. Screens own their forms;
`BatchReview` coordinates the viewer, queue, editor, dialogs, and publication
history. `useBatch` rejects stale responses. `useFaceSession` owns in-memory face
selectors, propagation previews, and expiry. `usePhotoSelection` owns filters
and ranges. Shared hooks provide feedback and unsaved-change guards.

Review remains mounted while hidden so polling and expiry continue. Opening an
album resets selection, and screen-opening state contains no face geometry.
A 401 clears private workspace state. Forms retain drafts across status refreshes
and integration-panel collapse. Python contracts generate the frontend schema;
see [Development](development.md#work-on-the-frontend).
