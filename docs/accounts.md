# Accounts and registration

Each account has a private workspace for its photos, rosters, and captions.
Administrators manage settings, invitations, registration, and Chevereto access.
They cannot browse other users' batches through the app. Server operators can
still access the underlying database and files.

Ordinary users can upload, analyze, and review photos. Chevereto imports,
connection settings, and publishing are available only to administrators.

## Create the first administrator

Start the deployment, then retrieve its one-time setup code:

```sh
docker compose --env-file .env.docker run --rm ops setup-code
```

Open Startnummer, enter the code, and choose a username and password. Usernames
use 3–64 letters, numbers, dots, underscores, or hyphens and are compared without
case. Passwords need at least 12 characters.

The first account becomes administrator. Setup is disabled once it exists;
concurrent requests cannot create several first administrators. The code is
available only through the local command while setup is incomplete. Share it
only with the person creating that account.

For a native installation, run `uv run --no-sync startnummer setup-code`.

## Invite a user

1. Open **Administration → Accounts and invitations**.
2. Enter an invitation label and an expiry in hours. The default is 48 hours;
   the allowed range is 1–168.
3. Choose **Create invitation link**, then **Copy link**.
4. Send the link privately to the person who should register.

The complete link is shown only when created. It creates one ordinary account
and cannot be reused after registration, expiry, or revocation. Invitations work
while public registration is closed. Use **Revoke invitation** to cancel a link;
creating another link does not cancel the old one.

## Open or close public registration

Under **Accounts and invitations**, change **Allow public registration** and
choose **Save registration**. Registration is closed by default.

Enabling it adds account creation to the sign-in page. Disabling it stops new
public sign-ups; existing accounts and unexpired invitations still work. New
accounts are ordinary users. This version has no SMTP delivery, email verification,
or forgotten-password flow.

## Change a password or revoke sessions

Open **Account** to change your password or choose **Sign out all sessions**.
Changing a password signs out other browsers and replaces the current session.
Ordinary **Sign out** ends only that browser's session. Administrators can also
use **Revoke sessions for…** in the account list.

These actions cancel that user's active analysis and discard temporary face data.
Saved albums and captions remain. The browser clears its workspace on the next
failed authentication check; open workspaces check every 30 seconds and when the
window regains focus. Offline browsers notice revocation when they reconnect.

Sessions expire after 12 hours. Use `STARTNUMMER_COOKIE_SECURE=1` behind HTTPS;
use `0` only for local HTTP tests. See [authentication details](architecture.md#accounts-and-secrets)
for password storage, token handling, and rate limits.

## Use an environment-configured account

To use the setup page, leave `STARTNUMMER_USERNAME` and `STARTNUMMER_PASSWORD`
unset on a new installation.

If both are already configured, Startnummer creates the administrator from those
credentials on first startup. Sign in once, then remove `STARTNUMMER_PASSWORD`
from server configuration and recreate the API. Make future password changes
under **Account**. Leaving the environment password configured does not override
the stored password.

This imports account credentials, not an older database schema. The first-release
baseline is revision `1`; older pre-release databases cannot be upgraded in place.
Use a fresh database, or [restore an archive](backups.md#test-a-recovery) into a
separate empty installation when you need to retain saved work.

## Recover an account

[Application archives](backups.md) preserve the username and original owner UUID,
but exclude password hashes, sessions, invitations, and registration policy.
Recovery requires an empty installation. Complete setup with the archived
username and a new password; that account becomes administrator of the recovered
installation. Archives cannot be merged into an existing multi-user deployment.

When using an old environment file for recovery, remove its legacy password or
retain the exact archived username. A mismatched legacy account is rejected
instead of creating an administrator without access to the recovered albums.
