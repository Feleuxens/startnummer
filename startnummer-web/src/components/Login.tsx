import { useEffect, useState } from 'react';
import type { Schema } from '../api/types';

type Credentials = { username: string; password: string; code?: string; invitation?: string };

export default function Login({
  status,
  onSubmit,
  error,
  busy,
}: {
  status: Schema['AuthStatus'];
  onSubmit: (mode: 'login' | 'setup' | 'register', credentials: Credentials) => Promise<void>;
  error: string;
  busy: boolean;
}) {
  const [invitation, setInvitation] = useState(
    () => window.location.hash.match(/^#invite\/([A-Za-z0-9_-]{43})$/)?.[1],
  );
  const [register, setRegister] = useState(Boolean(invitation));
  const [confirmationError, setConfirmationError] = useState('');
  useEffect(() => {
    const update = () => {
      const token = window.location.hash.match(/^#invite\/([A-Za-z0-9_-]{43})$/)?.[1];
      setInvitation(token);
      setRegister(Boolean(token));
      setConfirmationError('');
    };
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  const mode = status.setup_required ? 'setup' : register ? 'register' : 'login';
  const creating = mode !== 'login';
  const title =
    mode === 'setup'
      ? 'Set up Startnummer'
      : creating
        ? 'Create your account'
        : 'Your photos. The right names.';
  return (
    <main className="login">
      <div className="brand">
        <span className="bib-mark" aria-hidden="true">
          #
        </span>
        Startnummer
      </div>
      <h1>{title}</h1>
      <p>
        {mode === 'setup'
          ? 'Create the first administrator with the setup code from your server.'
          : creating
            ? invitation
              ? 'Your invitation creates an account with a private workspace.'
              : 'Create an account to import, analyze, and review your photos.'
            : 'Sign in to import, analyze, and review your sports photo captions.'}
      </p>
      <form
        key={`${mode}:${invitation ?? ''}`}
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const password = String(data.get('password'));
          if (creating && password !== data.get('confirmation')) {
            setConfirmationError('The passwords do not match.');
            return;
          }
          setConfirmationError('');
          void onSubmit(mode, {
            username: String(data.get('username')),
            password,
            ...(mode === 'setup' ? { code: String(data.get('code')) } : {}),
            ...(mode === 'register' && invitation ? { invitation } : {}),
          });
        }}
      >
        {mode === 'setup' && (
          <label>
            Setup code
            <input name="code" autoComplete="off" required spellCheck={false} />
          </label>
        )}
        <label>
          Username
          <input
            name="username"
            aria-label="Username"
            autoComplete="username"
            required
            minLength={creating ? 3 : undefined}
            maxLength={64}
            pattern={creating ? '[A-Za-z0-9][A-Za-z0-9._\\-]{2,63}' : undefined}
          />
          {creating && <small>3–64 letters, numbers, dots, underscores, or hyphens.</small>}
        </label>
        <label>
          Password
          <input
            name="password"
            aria-label="Password"
            type="password"
            autoComplete={creating ? 'new-password' : 'current-password'}
            required
            minLength={creating ? 12 : undefined}
            maxLength={1024}
          />
          {creating && <small>Use at least 12 characters.</small>}
        </label>
        {creating && (
          <label>
            Confirm password
            <input
              name="confirmation"
              type="password"
              autoComplete="new-password"
              required
              maxLength={1024}
            />
          </label>
        )}
        {(confirmationError || error) && (
          <p role="alert" className="error-text">
            {confirmationError || error}
          </p>
        )}
        <button className="primary" disabled={busy}>
          {busy
            ? 'Please wait…'
            : mode === 'setup'
              ? 'Create administrator'
              : creating
                ? 'Create account'
                : 'Sign in'}
        </button>
      </form>
      {!status.setup_required && (register || status.registration_enabled) && (
        <button
          className="auth-switch"
          disabled={busy}
          onClick={() => {
            setRegister(!register);
            setConfirmationError('');
          }}
        >
          {register ? 'Already have an account? Sign in' : 'Create an account'}
        </button>
      )}
      {mode === 'setup' && (
        <p className="muted">
          The server operator can retrieve the one-time code with{' '}
          <code>startnummer setup-code</code>.
        </p>
      )}
    </main>
  );
}
