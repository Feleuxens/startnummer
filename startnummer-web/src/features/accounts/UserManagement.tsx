import { useEffect, useRef, useState } from 'react';
import type { Schema } from '../../api/types';
import { api, message, unwrap } from '../../api/client';

export default function UserManagement({ onDirty }: { onDirty: (dirty: boolean) => void }) {
  const [data, setData] = useState<Schema['AccountAdministration'] | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [link, setLink] = useState('');
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  const dirty = useRef(false);
  async function load() {
    const result = unwrap(await api.GET('/api/admin/accounts'));
    if (!alive.current) return;
    setData((current) =>
      dirty.current && current
        ? {
            ...result,
            revision: current.revision,
            registration_enabled: current.registration_enabled,
          }
        : result,
    );
    if (!dirty.current) setEnabled(result.registration_enabled);
  }
  async function run(work: () => Promise<void>) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await work();
    } catch (failure) {
      if (alive.current) setError(message(failure));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    void run(load);
    return () => {
      alive.current = false;
    };
  }, []);
  return (
    <section className="user-management" aria-labelledby="accounts-title">
      <div className="title-row">
        <h2 id="accounts-title">Accounts and invitations</h2>
        <button disabled={busy} onClick={() => void run(load)}>
          Refresh accounts
        </button>
      </div>
      {error && (
        <p className="message error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="message" role="status">
          {notice}
        </p>
      )}
      {!data && !error && <p role="status">Loading accounts…</p>}
      {data && (
        <>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void run(async () => {
                const saved = unwrap(
                  await api.PUT('/api/admin/registration', {
                    body: { revision: data.revision, registration_enabled: enabled },
                  }),
                );
                if (!alive.current) return;
                dirty.current = false;
                onDirty(false);
                setData({ ...data, ...saved });
                setNotice('Registration settings saved.');
              });
            }}
          >
            <label className="check-row">
              <input
                type="checkbox"
                checked={enabled}
                disabled={busy}
                onChange={(event) => {
                  setEnabled(event.target.checked);
                  dirty.current = true;
                  onDirty(true);
                }}
              />
              Allow public registration
            </label>
            <p className="muted">
              Registration is closed by default. Invitations work while it is closed. New accounts
              are ordinary users with private batches; Chevereto access stays with the
              administrator.
            </p>
            <button disabled={busy || !dirty.current}>Save registration</button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (dirty.current && !window.confirm('Discard unsaved registration settings?'))
                  return;
                dirty.current = false;
                onDirty(false);
                void run(load);
              }}
            >
              Reload registration
            </button>
          </form>
          <h3>Create invitation</h3>
          <form
            className="invitation-form"
            onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget;
              const values = new FormData(form);
              void run(async () => {
                const created = unwrap(
                  await api.POST('/api/admin/invitations', {
                    body: {
                      label: String(values.get('label')),
                      hours: Number(values.get('hours')),
                    },
                  }),
                );
                if (!alive.current) return;
                setLink(
                  `${window.location.origin}${window.location.pathname}#invite/${created.token}`,
                );
                form.reset();
                await load();
              });
            }}
          >
            <fieldset disabled={busy}>
              <label>
                Invitation label
                <input name="label" maxLength={120} placeholder="Who is this for?" />
              </label>
              <label>
                Expires after (hours)
                <input name="hours" type="number" min={1} max={168} defaultValue={48} required />
              </label>
              <button>Create invitation link</button>
            </fieldset>
          </form>
          {link && (
            <div className="invitation-link">
              <label>
                Invitation link
                <input value={link} readOnly onFocus={(event) => event.currentTarget.select()} />
              </label>
              <button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await navigator.clipboard.writeText(link);
                    if (alive.current) setNotice('Invitation link copied.');
                  })
                }
              >
                Copy link
              </button>
              <p className="muted">
                Copy this link now. It is shown only here and can be used once.
              </p>
            </div>
          )}
          <h3>Invitations</h3>
          {data.invitations.length ? (
            <ul className="account-list">
              {data.invitations.map((invitation) => (
                <li key={invitation.id}>
                  <div>
                    <strong>{invitation.label || 'Invitation'}</strong>
                    <span>
                      {invitation.state} · expires{' '}
                      {new Date(invitation.expires_at).toLocaleString()}
                    </span>
                  </div>
                  {invitation.state === 'available' && (
                    <button
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          unwrap(
                            await api.DELETE('/api/admin/invitations/{invitation_id}', {
                              params: { path: { invitation_id: invitation.id } },
                            }),
                          );
                          setLink('');
                          await load();
                        })
                      }
                    >
                      Revoke invitation
                    </button>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No invitations yet.</p>
          )}
          <h3>Users</h3>
          <ul className="account-list">
            {data.users.map((user) => (
              <li key={user.id}>
                <div>
                  <strong>{user.username}</strong>
                  <span>{user.is_admin ? 'Administrator' : 'User'}</span>
                </div>
                <button
                  disabled={busy}
                  onClick={() => {
                    if (
                      !window.confirm(
                        `Sign out all sessions for ${user.username}? Active analysis will be cancelled and temporary face data cleared.`,
                      )
                    )
                      return;
                    void run(async () => {
                      unwrap(
                        await api.DELETE('/api/admin/users/{user_id}/sessions', {
                          params: { path: { user_id: user.id } },
                        }),
                      );
                      if (alive.current) setNotice(`Sessions revoked for ${user.username}.`);
                    });
                  }}
                >
                  Revoke sessions for {user.username}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
