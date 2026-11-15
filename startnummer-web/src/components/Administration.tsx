import { useEffect, useRef, useState } from 'react';
import type { SubmitEvent } from 'react';
import type { components } from '../api/schema';
import { api, message, unwrap } from '../api/client';
import CheveretoIntegration from '../features/integrations/CheveretoIntegration';

type Schema = components['schemas'];
const MiB = 1024 * 1024;
const editable = (settings: Schema['RuntimeSettings']) => ({
  revision: settings.revision ?? 0,
  file: String(settings.max_file_bytes / MiB),
  batch: String(settings.max_batch_bytes / MiB),
  minutes: String(settings.session_ttl / 60),
});

export default function Administration({
  onIntegrationChange,
  onDirty,
}: {
  onIntegrationChange: () => void;
  onDirty: (dirty: boolean) => void;
}) {
  const [data, setData] = useState<Schema['Administration'] | null>(null);
  const [form, setForm] = useState<ReturnType<typeof editable> | null>(null);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const dirty = useRef(false);
  const integrationDirty = useRef(false);
  const alive = useRef(true);
  async function refresh() {
    try {
      const result = unwrap(await api.GET('/api/admin'));
      if (!alive.current) return;
      setData(result);
      if (!dirty.current) setForm(editable(result.settings));
      setLoadError('');
    } catch (failure) {
      if (alive.current) setLoadError(message(failure));
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
  async function save(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const saved = unwrap(
        await api.PUT('/api/admin/settings', {
          body: {
            revision: form.revision,
            max_file_bytes: Math.round(Number(form.file) * MiB),
            max_batch_bytes: Math.round(Number(form.batch) * MiB),
            session_ttl: Math.round(Number(form.minutes) * 60),
          },
        }),
      );
      if (!alive.current) return;
      dirty.current = false;
      onDirty(integrationDirty.current);
      setForm(editable(saved));
      setNotice(
        'Settings saved. Import limits apply to new imports; the lifetime applies to new face sessions.',
      );
      await refresh();
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="administration">
      <div className="title-row">
        <div>
          <h1>Administration</h1>
          <p>Service status and settings for this installation.</p>
        </div>
        <button disabled={busy} onClick={() => void refresh()}>
          Refresh status
        </button>
      </div>
      {(error || loadError) && (
        <p className="message error" role="alert">
          {error || loadError}
        </p>
      )}
      {notice && (
        <p className="message" role="status">
          {notice}
        </p>
      )}
      {!data && !error && <p role="status">Loading service status…</p>}
      {data && form && (
        <>
          <section aria-labelledby="services-title">
            <h2 id="services-title">Services</h2>
            <dl className="service-status">
              <div>
                <dt>API</dt>
                <dd>Running</dd>
              </div>
              <div>
                <dt>Database</dt>
                <dd>{data.database ? 'Available' : 'Unavailable'}</dd>
              </div>
              <div>
                <dt>Photo storage</dt>
                <dd>{data.storage ? 'Writable' : 'Unavailable'}</dd>
              </div>
              <div>
                <dt>Analysis worker</dt>
                <dd>{data.worker.state}</dd>
              </div>
              <div>
                <dt>Active face sessions</dt>
                <dd>{data.worker.active_sessions ?? 0}</dd>
              </div>
            </dl>
            <p className="muted">
              {data.jobs.queued ?? 0} queued · {data.jobs.running ?? 0} running ·{' '}
              {data.jobs.failed ?? 0} failed jobs
            </p>
            {!data.worker.reachable && (
              <p className="muted">The worker is unavailable. Saved captions remain editable.</p>
            )}
          </section>
          <section aria-labelledby="integrations-title">
            <h2 id="integrations-title">Configured integrations</h2>
            <CheveretoIntegration
              onDirty={(value) => {
                integrationDirty.current = value;
                onDirty(dirty.current || value);
              }}
              onChanged={onIntegrationChange}
            />
          </section>
          <section aria-labelledby="settings-title">
            <h2 id="settings-title">Import and face review</h2>
            <form onSubmit={(event) => void save(event)}>
              <fieldset
                disabled={busy || !data.database}
                onChange={() => {
                  dirty.current = true;
                  onDirty(true);
                }}
              >
                <label>
                  Maximum photo size (MiB)
                  <input
                    type="number"
                    min="1"
                    max="500"
                    step="any"
                    required
                    value={form.file}
                    onChange={(event) => {
                      dirty.current = true;
                      setForm({ ...form, file: event.target.value });
                    }}
                  />
                </label>
                <label>
                  Maximum batch size (MiB)
                  <input
                    type="number"
                    min={Number(form.file) || 1}
                    max="102400"
                    step="any"
                    required
                    value={form.batch}
                    onChange={(event) => {
                      dirty.current = true;
                      setForm({ ...form, batch: event.target.value });
                    }}
                  />
                </label>
                <label>
                  Face-session lifetime (minutes)
                  <input
                    type="number"
                    min="1"
                    max="1440"
                    step="any"
                    required
                    value={form.minutes}
                    onChange={(event) => {
                      dirty.current = true;
                      setForm({ ...form, minutes: event.target.value });
                    }}
                  />
                </label>
                <p className="muted">
                  Changing the lifetime affects new sessions. Existing sessions keep their expiry.
                  Finishing review, signing out, cancelling, deleting a batch, or stopping the
                  worker clears temporary face data.
                </p>
                <button className="primary" disabled={busy} type="submit">
                  {busy ? 'Saving…' : 'Save settings'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (
                      dirty.current &&
                      !window.confirm('Discard unsaved settings and load the saved values?')
                    )
                      return;
                    dirty.current = false;
                    onDirty(integrationDirty.current);
                    setError('');
                    void refresh();
                  }}
                >
                  Reload settings
                </button>
              </fieldset>
            </form>
          </section>
          <section aria-labelledby="maintenance-title">
            <h2 id="maintenance-title">Backups and maintenance</h2>
            <p>
              Use the local <code>startnummer backup</code> and <code>startnummer restore</code>{' '}
              commands. Backups include saved photos, rosters, review decisions, publishing history,
              and these settings. Temporary face data and gallery credentials are excluded.
            </p>
            <p className="muted">
              Startnummer's database connection and storage paths remain in server configuration.
              Restore requires an empty destination and does not change Chevereto.
            </p>
          </section>
        </>
      )}
    </div>
  );
}
