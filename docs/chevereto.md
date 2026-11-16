# Connect Chevereto

Startnummer updates descriptions on existing **Chevereto 4.5.9** images using its
`chv_` tables. It needs the gallery URL and access to the gallery's MariaDB database.
Only the administrator can use this connection.

## Configure the connection in Administration

1. Check that `STARTNUMMER_INTEGRATION_KEY` is set on the API. The
   [Docker quick start](docker.md#2-set-passwords-and-secrets) generates this key.
2. Remove both `STARTNUMMER_CHEVERETO_URL` and `STARTNUMMER_CHEVERETO_DSN` from the
   API environment file. Empty values still select environment management.
3. Recreate the API if you changed its environment:

   ```sh
   docker compose --env-file .env.docker up -d api
   ```

4. Sign in and open **Administration → Configured integrations → Chevereto**.
5. Enter the gallery URL, database host, port, database name, username, and password.
6. Choose **Test connection**, then **Save connection**.

**Test connection** checks reads and the supported schema; it does not verify
permission to update descriptions. To check publishing, use a test gallery photo,
apply one reviewed description, check the rendered gallery page, and restore it.

Saved changes apply to new gallery operations without an API restart. When editing
an existing connection, leave the password blank to retain it. The browser never
receives the stored password. Collapsing the settings panel keeps unsaved edits.

For a native installation, generate a Fernet key with:

```sh
uv run --no-sync python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Keep it separate from the session and worker secrets. If it is lost or changed,
re-enter the connection under a new key; the old encrypted credentials cannot be
read without the original key.

## Configure the connection through the environment

Set both values in `.env.docker` or the native API's environment:

```dotenv
STARTNUMMER_CHEVERETO_URL=https://gallery.example.org
STARTNUMMER_CHEVERETO_DSN=mysql://startnummer:password@gallery-db:3306/chevereto
```

Replace the example credentials and URL-encode special characters in the DSN.
Use a database account with the permissions needed for reads and description
updates.

The panel will show **Managed by environment** and its fields will be read-only.
Presence of either variable selects this mode for the whole connection, including
an empty or incomplete value. Invalid environment settings produce an error;
they do not fall back to saved credentials. Removing both variables reactivates
any saved connection.

## Reach the database from Docker

Use a host reachable from the API container. `localhost` inside that container
refers to the container itself. If the gallery database is another container,
connect the API to its network and use the database service name.

The worker needs Startnummer's database and photos, but no gallery credentials.
Keep the worker port private. Chevereto imports support local datefolder, direct,
and path image storage; external and legacy storage modes are unsupported.

## Keep saved albums bound to the right gallery

Gallery imports record the remote image ID, imported description, and an identity
derived from Chevereto's installation salt. Startnummer checks that identity
before reading or writing descriptions. Changing a URL or database connection
cannot silently redirect a saved album to another gallery. A database clone with
the same salt has the same identity.

For older batches without an identity, use **Confirm gallery for older batches…**
after checking the configured destination. This binds the gallery without changing
captions, approvals, or descriptions.

[Application backups](backups.md) keep these bindings but exclude connection
credentials and encryption keys. Reconfigure gallery access after restoring.
For the publishing workflow and conflict recovery, see [Review an album](review.md#5-apply-descriptions-to-chevereto).
