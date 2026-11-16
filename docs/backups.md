# Back up and restore

A Startnummer archive contains one account's saved work and referenced photos.
Create a separate archive for each account, and keep copies away from the server.

| Included                                         | Excluded                                    |
| ------------------------------------------------ | ------------------------------------------- |
| Photos, roster, and analysis                     | Temporary face data and model weights       |
| Names, reviewed captions, and approvals          | Password hashes, sessions, and invitations  |
| Jobs and publication history                     | Registration policy and gallery credentials |
| Account username and original owner UUID         | Environment files and encryption keys       |
| That account's saved limits and gallery identity | Chevereto's database and images             |

Keep server configuration and key material separately. Application archives do not
back up the whole account registry. To recover an entire multi-user installation
with its authentication state, you also need a PostgreSQL backup and the photo
storage/configuration; the archive restore command recovers one account into an
empty installation.

## Create an archive

Run these commands from the deployment directory:

```sh
docker compose --env-file .env.docker run --rm ops backup /backups/startnummer.snbak
docker compose --env-file .env.docker run --rm ops verify-backup /backups/startnummer.snbak
```

The default account is the administrator. Add `--username NAME` to back up another
user:

```sh
docker compose --env-file .env.docker run --rm ops backup /backups/guest.snbak --username guest
```

Choose a new filename each time. Startnummer refuses to replace an archive.
Verification checks the manifest, record ownership, and file checksums.

PostgreSQL backups can run while the app is up. Imports, edits, and cleanup for
that account wait while its photo bytes are copied; worker lease heartbeats
continue. SQLite backups are for offline development only.

## Copy the archive off the server

The archive is in Docker's backup volume. Copy it to a host file:

```sh
umask 077
docker compose --env-file .env.docker run --rm -T --no-deps \
  --entrypoint cat ops /backups/startnummer.snbak > startnummer.snbak
```

Check the resulting file and copy it to your backup storage. Keep the environment
file and integration encryption key in a separate protected backup.

## Test a recovery

Use a separate terminal and a new Compose project so recovery cannot overwrite
an existing database or photo directory. These steps assume the source project's
backup volume is named `startnummer_backups`. Check it with `docker volume ls` and
substitute the actual name if your source project differs.

### 1. Prepare the recovery configuration

```sh
cp .env.docker .env.docker.recovery
chmod 600 .env.docker.recovery
export STARTNUMMER_ENV_FILE="$PWD/.env.docker.recovery"
```

Edit the recovery file before continuing:

- Set `STARTNUMMER_PORT=8001` so it can run beside the original API.
- Remove `STARTNUMMER_PASSWORD` and both `STARTNUMMER_CHEVERETO_*` connection
  variables. You will create a new password and review the restored work before
  reconnecting a gallery.
- Set `STARTNUMMER_COOKIE_SECURE=0` if you will test through local HTTP. Keep the
  loopback bind address.

`STARTNUMMER_ENV_FILE` selects the API's environment file. The `--env-file` argument
below selects the same file for Compose variables.

### 2. Restore into empty volumes

```sh
docker compose --env-file "$STARTNUMMER_ENV_FILE" -p startnummer-recovery up -d --wait postgres
docker compose --env-file "$STARTNUMMER_ENV_FILE" -p startnummer-recovery run --rm \
  -v startnummer_backups:/backups:ro --entrypoint sh ops -c \
  'exec python -m startnummer.app.manage restore /backups/startnummer.snbak \
    --database-url "$STARTNUMMER_DATABASE_URL" --blob-root "$STARTNUMMER_BLOB_ROOT"'
```

The restore verifies the archive, migrates the empty database, and restores the
original owner UUID and photo IDs. Queued or running jobs become cancelled. It
refuses existing records, initialized account registries, unrelated tables, and
nonempty photo destinations.

If recovery is interrupted, retry into another empty destination. Prepared photo
bytes may be retained after an uncertain database commit so committed references
cannot point to missing files.

### 3. Open the recovered account

```sh
docker compose --env-file "$STARTNUMMER_ENV_FILE" -p startnummer-recovery up -d --wait
docker compose --env-file "$STARTNUMMER_ENV_FILE" -p startnummer-recovery run --rm ops setup-code
```

Open <http://localhost:8001>. Use the setup code, the archived username, and a new
password. The recovered account becomes administrator of this separate
installation. Reopen an album and check its photos and reviewed captions.

Restore does not merge an archive into an existing multi-user installation and
does not restore or change Chevereto descriptions. Reconnect the intended gallery
only after checking the recovered work. Use **Check gallery outcome** to reconcile
uncertain writes before applying descriptions again.

New archives use format 3; formats 1 and 2 remain readable. Older archives have no
username field, so retain the original username when completing setup.

## Use the native commands

For an installed native app, the same operations run through the launcher CLI:

```sh
uv run --no-sync startnummer backup /path/to/backups/startnummer.snbak
uv run --no-sync startnummer verify-backup /path/to/backups/startnummer.snbak
uv run --no-sync startnummer restore /path/to/backups/startnummer.snbak \
  --database-url sqlite:////tmp/startnummer-recovered.db \
  --blob-root /tmp/startnummer-recovered-photos
```

This restore example creates an offline development copy. For a running app,
provide a dedicated empty PostgreSQL database and empty photo directory. Point
its server configuration at those destinations before starting it and completing
setup. If the CLI is unavailable, `uv run --no-sync python -m
startnummer.app.manage ...` runs the same commands.
