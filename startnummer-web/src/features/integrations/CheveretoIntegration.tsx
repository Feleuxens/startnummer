import { useEffect, useRef, useState } from 'react';
import type { SubmitEvent } from 'react';
import type { Schema } from '../../api/types';
import { message } from '../../api/client';
import { getConnection, saveConnection, testConnection, confirmLegacy } from './api';
import IntegrationPanel from './IntegrationPanel';

type Status = Schema['IntegrationStatus'];
const editable = (status: Status) => ({
  revision: status.revision ?? 0,
  url: status.url ?? '',
  host: status.host ?? '',
  port: status.port ?? 3306,
  database: status.database ?? '',
  username: status.username ?? '',
  password: '',
});

export default function CheveretoIntegration({
  onDirty,
  onChanged,
}: {
  onDirty: (dirty: boolean) => void;
  onChanged: () => void;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [form, setForm] = useState<ReturnType<typeof editable> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const dirty = useRef(false);
  const alive = useRef(true);

  function load(result: Status) {
    setStatus(result);
    setForm(editable(result));
    dirty.current = false;
    onDirty(false);
  }
  async function refresh() {
    try {
      const result = await getConnection();
      if (!alive.current) return;
      setStatus(result);
      if (!dirty.current || result.source === 'environment') load(result);
    } catch (failure) {
      if (alive.current) setError(message(failure));
    }
  }
  useEffect(() => {
    alive.current = true;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
    };
  }, []);

  function request(): Schema['CheveretoConnection'] {
    if (!form) throw new Error('Wait for the connection to load.');
    return { ...form, password: form.password === '' ? null : form.password };
  }
  async function run(operation: () => Promise<void>) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await operation();
    } catch (failure) {
      if (alive.current) setError(message(failure));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  function save(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(async () => {
      const result = await saveConnection(request());
      if (!alive.current) return;
      load(result);
      setNotice('Connection saved. New gallery operations use this configuration.');
      onChanged();
    });
  }

  const environment = status?.source === 'environment';
  const state = busy
    ? 'Working…'
    : error || status?.error
      ? 'Needs attention'
      : dirty.current
        ? 'Unsaved changes'
        : status?.configured
          ? 'Configured'
          : 'Not configured';
  const description = status
    ? `${state} · ${environment ? 'Managed by environment' : 'Managed in Administration'}`
    : error
      ? 'Needs attention'
      : 'Loading connection…';
  return (
    <IntegrationPanel name="Chevereto" description={description}>
      {!status && !error && <p role="status">Loading connection…</p>}
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
      {status && form && (
        <>
          {status.url && (
            <p>
              <a href={status.url}>{status.url}</a>
            </p>
          )}
          {status.error && (
            <p className="message error" role="alert">
              {status.error}
            </p>
          )}
          <form onSubmit={save} autoComplete="off">
            <fieldset
              disabled={busy || !status.editable}
              onChange={() => {
                dirty.current = true;
                onDirty(true);
              }}
            >
              <label>
                Gallery URL
                <input
                  type="url"
                  required
                  maxLength={2048}
                  value={form.url}
                  onChange={(event) => setForm({ ...form, url: event.target.value })}
                />
              </label>
              <label>
                Database host
                <input
                  required
                  maxLength={255}
                  value={form.host}
                  onChange={(event) => setForm({ ...form, host: event.target.value })}
                />
              </label>
              <label>
                Database port
                <input
                  type="number"
                  required
                  min={1}
                  max={65535}
                  value={form.port}
                  onChange={(event) => setForm({ ...form, port: Number(event.target.value) })}
                />
              </label>
              <label>
                Database name
                <input
                  required
                  maxLength={255}
                  value={form.database}
                  onChange={(event) => setForm({ ...form, database: event.target.value })}
                />
              </label>
              <label>
                Database username
                <input
                  required
                  maxLength={255}
                  autoComplete="off"
                  value={form.username}
                  onChange={(event) => setForm({ ...form, username: event.target.value })}
                />
              </label>
              <label>
                Database password
                <input
                  type="password"
                  autoComplete="new-password"
                  required={!status.password_set}
                  value={form.password}
                  placeholder={
                    environment
                      ? 'Set by environment'
                      : status.password_set
                        ? 'Leave blank to keep the saved password'
                        : ''
                  }
                  onChange={(event) => setForm({ ...form, password: event.target.value })}
                />
              </label>
            </fieldset>
            <div className="actions integration-actions">
              <button
                type="button"
                disabled={busy || (environment ? !status.configured : !status.editable)}
                onClick={() =>
                  void run(async () => {
                    const result = await testConnection(environment ? undefined : request());
                    if (alive.current) setNotice(result.message ?? 'Connection verified.');
                  })
                }
              >
                {busy ? 'Checking…' : 'Test connection'}
              </button>
              {!environment && (
                <>
                  <button type="submit" className="primary" disabled={busy || !status.editable}>
                    Save connection
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      if (
                        dirty.current &&
                        !window.confirm('Discard unsaved connection changes and reload?')
                      )
                        return;
                      dirty.current = false;
                      onDirty(false);
                      setError('');
                      setNotice('');
                      void refresh();
                    }}
                  >
                    Reload connection
                  </button>
                </>
              )}
            </div>
          </form>
          {Boolean(status.legacy_photos) && !status.legacy_confirmed && (
            <>
              <p>
                {status.legacy_photos} older photos have no verified gallery identity. Confirm their
                gallery before publishing or restoring descriptions.
              </p>
              <button
                type="button"
                disabled={busy || dirty.current || !status.configured}
                onClick={() => {
                  if (
                    !window.confirm(
                      `Confirm that the ${status.legacy_photos} older photos were imported from ${status.url}? This records the gallery identity without writing descriptions.`,
                    )
                  )
                    return;
                  void run(async () => {
                    const result = await confirmLegacy(status.revision ?? 0);
                    if (!alive.current) return;
                    load(result);
                    setNotice('Gallery confirmed for older batches. No descriptions were written.');
                  });
                }}
              >
                Confirm gallery for older batches…
              </button>
            </>
          )}
        </>
      )}
    </IntegrationPanel>
  );
}
