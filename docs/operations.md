# Operate Startnummer

Use this guide to check a running installation, change limits, or update it.
For a new installation, start with the [Docker quick start](docker.md).

## Check service status

Run these commands from the deployment directory:

```sh
docker compose --env-file .env.docker ps -a
docker compose --env-file .env.docker logs --tail=100 api worker migrate
```

The API, worker, and PostgreSQL should be healthy, and `migrate` should have exited
with code 0. **Administration** shows storage status, queue counts, and active
face sessions. It also lists configured integrations.

Read the API readiness response if its container is unhealthy:

```sh
docker compose --env-file .env.docker exec -T api python -c \
  'import httpx; print(httpx.get("http://127.0.0.1:8000/api/health/ready", timeout=5, trust_env=False).text)'
```

| Field      | What it checks                                                   |
| ---------- | ---------------------------------------------------------------- |
| `database` | PostgreSQL access and required tables                            |
| `storage`  | Creating, writing, and syncing a temporary file in photo storage |
| `ready`    | Both database and storage checks passed                          |

The worker has its own authenticated health check. Health checks do not load
models or test the gallery connection. Analyze a small album to check inference;
use **Test connection** in Administration to check Chevereto reads.

## Change import and face-review limits

Open **Administration → Import and face review**, edit the values, and choose
**Save settings**.

| Setting               | Default    | Applies to        |
| --------------------- | ---------- | ----------------- |
| Maximum photo size    | 50 MiB     | New imports       |
| Maximum batch size    | 2 GiB      | New imports       |
| Face-session lifetime | 60 minutes | New face sessions |

Existing face sessions keep their expiry. If another browser saved settings first,
reload the saved values before editing again. For larger imports, adjust the
[proxy upload limit](reverse-proxy.md#upload-limits-and-timeouts) and temporary
storage budget too.

## Check persistent storage

Compose creates these named volumes under your project name:

| Volume     | Contents                                       | Application access                  |
| ---------- | ---------------------------------------------- | ----------------------------------- |
| `postgres` | Startnummer records and accounts               | PostgreSQL's own image user         |
| `photos`   | Imported originals at `/data/photos/originals` | API writes; worker reads            |
| `models`   | Downloaded weights and converted models        | Worker writes                       |
| `backups`  | Application archives                           | API and operations containers write |

Application containers run as UID/GID `1000:1000`. Fresh named volumes inherit
that ownership from the image. For bind mounts, prepare the host directories for
this identity. To use another identity, adjust the commented `user:` line in
`x-runtime` in `compose.yaml`. It applies to API, worker, migration, and operations
containers; PostgreSQL keeps its own user.

Changing an image or `user:` value does not change existing file ownership.
Volumes from earlier application images may belong to `10001:10001`. Adjust the
application mounts to the selected identity while preserving their contents.

If readiness reports `database: true` and `storage: false`, check photo-directory
ownership, writable access, and free space. Keep the storage directory beneath
the volume mount: restore needs to replace `/data/photos/originals`, and cannot
replace the `/data/photos` mount point itself.

Each application container has a read-only root filesystem and a 4 GiB
memory-backed `/tmp`. Analysis stages originals there. Budget memory for those
files, model buffers, inference, and the decoded-image cache (512 MiB by default).
Adjust tmpfs capacity and import limits together. Core dumps are disabled; host
swap needs separate configuration if memory must never be paged to disk.

## Update Startnummer

1. Finish active face review. Replacing the worker discards temporary face data.
2. [Back up](backups.md) each account you want to retain and save the current
   configuration and image version.
3. Update the checkout to the intended version and set its published image tag in
   `.env.docker`. Keep the project name, volumes, worker variant, and GPU settings.
4. Pull the images, stop the old application processes, and start the update:

   ```sh
   docker compose --env-file .env.docker pull
   docker compose --env-file .env.docker stop api worker
   docker compose --env-file .env.docker up -d --wait
   docker compose --env-file .env.docker ps -a
   ```

5. Check that migration exited with code 0, sign in, and reopen a saved album.

For source builds, use the [build command](docker.md#build-from-source) instead of
`pull`. If you use a proxy override, include it on every Compose command as shown
in the [proxy guide](reverse-proxy.md).

The old API and worker must be stopped before the new schema is applied. Do not
assume an older image can use a migrated schema; recovery may require restoring
a backup. The first-release baseline uses one migration at revision `1`. Older
pre-release revision IDs have no in-place upgrade path; use a fresh database or
[recover an archive into an empty installation](backups.md#test-a-recovery).

> **Keep your data:** `docker compose down` preserves named volumes; `down -v`
> deletes them. Keep the same project name during normal updates. Use a new
> project name only when you intend to create a separate installation.

## Troubleshoot startup

| Symptom                             | Check                                                                                                      |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Migration fails                     | Read `migrate` logs. It needs a valid database URL and access to PostgreSQL.                               |
| A secret is too short               | Set the named session/worker secret to at least 32 random characters and recreate the affected containers. |
| A numeric setting is invalid        | Correct the named value in the environment file.                                                           |
| API readiness has `database: false` | Check PostgreSQL health, the connection URL, and migration status.                                         |
| API readiness has `storage: false`  | Check [storage access](#check-persistent-storage) and free space.                                          |
| Analysis fails on first use         | Read worker logs; check weight downloads, free temporary space, and the selected runtime.                  |
| HTTPS sign-in or uploads fail       | Use the [proxy troubleshooting table](reverse-proxy.md#check-the-installation).                            |

Older images may report a generic `Operation failed (ValueError)` during migration
when a session or worker secret is too short, before connecting to PostgreSQL.
Changing the database hostname cannot resolve that configuration error.

## Run or stop a native installation

The native launcher manages one API and one worker:

```sh
uv run --no-sync startnummer start --detach
uv run --no-sync startnummer status
uv run --no-sync startnummer stop
```

It loads `.env`; existing environment variables take precedence. Use
`startnummer --env-file /path/to/config.env ...` to select another file.
Without `--detach`, it stays in the foreground. Detached logs are written to
`.startnummer/run/launcher.log`; `--run-dir` selects another runtime directory.

`status` exits with code 1 until the API is ready and the worker is idle or busy.
The launcher refuses occupied ports and only stops processes it started. It
restarts a failed child up to three times. Stop services before changing their
Python environment or applying migrations.

Use `start --help` for launcher options. `--port` and `--worker-port` choose local
ports, `--cache-mb` controls the decoded-image cache (`0` disables it), and
`--no-faces` disables face inference. A standalone worker's `--once` mode exits
after one job and discards its face sessions, so it is unsuitable for retaining
face selectors during interactive review.

Stopping a worker interrupts analysis and clears face sessions; saved captions
remain. An API restart can retain a compatible worker's face sessions. Run one
worker per installation until routing for temporary face sessions is available.
