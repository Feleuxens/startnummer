import { useId, useState } from 'react';
import { api, message, unwrap } from '../../api/client';
import type { Schema } from '../../api/types';

export default function UserPasswordReset({
  user,
  onClose,
  onSaved,
}: {
  user: Schema['UserInfo'];
  onClose: () => void;
  onSaved: (reviewCleared: boolean) => void;
}) {
  const title = useId();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  return (
    <dialog
      className="apply-dialog password-reset-dialog"
      aria-labelledby={title}
      ref={(node) => {
        if (node && !node.open) node.showModal();
      }}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <h2 id={title}>Reset password for {user.username}</h2>
      <p>This signs out all of their sessions and cancels any active analysis.</p>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const values = new FormData(event.currentTarget);
          const password = String(values.get('password'));
          if (password !== values.get('confirm')) {
            setError('The new passwords do not match.');
            return;
          }
          setError('');
          setBusy(true);
          try {
            const result = unwrap(
              await api.PUT('/api/admin/users/{user_id}/password', {
                params: { path: { user_id: user.id } },
                body: { administrator_password: String(values.get('administrator')), password },
              }),
            );
            onSaved(result.review_cleared);
          } catch (failure) {
            setError(message(failure));
            setBusy(false);
          }
        }}
      >
        <fieldset disabled={busy}>
          <label>
            Your administrator password
            <input
              name="administrator"
              type="password"
              autoComplete="current-password"
              maxLength={1024}
              required
            />
          </label>
          <label>
            New password (at least 12 characters)
            <input
              name="password"
              type="password"
              autoComplete="new-password"
              minLength={12}
              maxLength={1024}
              required
            />
          </label>
          <label>
            Confirm new password
            <input
              name="confirm"
              type="password"
              autoComplete="new-password"
              minLength={12}
              maxLength={1024}
              required
            />
          </label>
          {error && (
            <p className="message error" role="alert">
              {error}
            </p>
          )}
          <div className="actions">
            <button type="button" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="primary">
              {busy ? 'Resetting…' : 'Reset password'}
            </button>
          </div>
        </fieldset>
      </form>
    </dialog>
  );
}
