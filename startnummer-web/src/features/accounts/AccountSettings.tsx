import { useRef, useState, useEffect } from 'react';
import { api, message, unwrap } from '../../api/client';

export default function AccountSettings({
  onDirty,
  onSignedOut,
  onSessionsCleared,
}: {
  onDirty: (dirty: boolean) => void;
  onSignedOut: () => void;
  onSessionsCleared: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  return (
    <div className="administration account-settings">
      <h1>Account</h1>
      <section aria-labelledby="password-title">
        <h2 id="password-title">Change password</h2>
        <p>
          Changing your password signs out other sessions and clears temporary face data. Saved
          photos and captions stay available.
        </p>
        <form
          onChange={() => onDirty(true)}
          onSubmit={async (event) => {
            event.preventDefault();
            const form = event.currentTarget;
            const data = new FormData(form);
            setError('');
            setNotice('');
            if (data.get('password') !== data.get('confirmation')) {
              setError('The passwords do not match.');
              return;
            }
            if (
              !window.confirm(
                'Change password and sign out other sessions? Active analysis will be cancelled and temporary face data cleared.',
              )
            )
              return;
            setBusy(true);
            try {
              unwrap(
                await api.PUT('/api/account/password', {
                  body: {
                    current_password: String(data.get('current_password')),
                    password: String(data.get('password')),
                  },
                }),
              );
              if (!alive.current) return;
              onSessionsCleared();
              form.reset();
              onDirty(false);
              setNotice('Password changed. Other sessions have been signed out.');
            } catch (failure) {
              if (alive.current) setError(message(failure));
            } finally {
              if (alive.current) setBusy(false);
            }
          }}
        >
          <fieldset disabled={busy}>
            <label>
              Current password
              <input
                name="current_password"
                type="password"
                autoComplete="current-password"
                required
              />
            </label>
            <label>
              New password
              <input
                name="password"
                aria-label="New password"
                type="password"
                autoComplete="new-password"
                minLength={12}
                maxLength={1024}
                required
              />
              <small>Use at least 12 characters.</small>
            </label>
            <label>
              Confirm new password
              <input
                name="confirmation"
                type="password"
                autoComplete="new-password"
                maxLength={1024}
                required
              />
            </label>
            <button className="primary">Change password</button>
          </fieldset>
        </form>
      </section>
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
      <section aria-labelledby="sessions-title">
        <h2 id="sessions-title">Sessions</h2>
        <p>
          Sign out every browser, including this one. Active analysis will be cancelled and
          temporary face data cleared.
        </p>
        <button
          disabled={busy}
          onClick={async () => {
            if (!window.confirm('Sign out all sessions and discard temporary face data?')) return;
            setBusy(true);
            setError('');
            try {
              unwrap(await api.DELETE('/api/account/sessions'));
              onSignedOut();
            } catch (failure) {
              if (alive.current) setError(message(failure));
            } finally {
              if (alive.current) setBusy(false);
            }
          }}
        >
          Sign out all sessions
        </button>
      </section>
    </div>
  );
}
