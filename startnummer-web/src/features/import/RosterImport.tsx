import { useEffect, useRef, useState } from 'react';
import type { Schema } from '../../api/types';
import { importProblem, previewRoster } from '../../api/workspace';
import { nameOrders } from './model';
import RosterNamePreview from './RosterNamePreview';

export default function RosterImport({
  busy,
  onBusyChange,
  importError,
  onEdit,
}: {
  busy: boolean;
  onBusyChange: (busy: boolean) => void;
  importError?: string;
  onEdit: () => void;
}) {
  const [source, setSource] = useState('file');
  const [order, setOrder] = useState<Schema['NameOrder']>('auto');
  const [url, setUrl] = useState('');
  const [preview, setPreview] = useState<Schema['RosterPreview'] | null>(null);
  const [corrections, setCorrections] = useState<Record<number, string>>({});
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  const visibleError = importError || error;
  useEffect(
    () => () => {
      generation.current += 1;
    },
    [],
  );

  function invalidate() {
    generation.current += 1;
    setPreview(null);
    setCorrections({});
    setError('');
    setLoading(false);
    onBusyChange(false);
    onEdit();
  }

  async function loadPreview() {
    if (
      Object.keys(corrections).length &&
      !window.confirm(
        'Reading the roster again clears the name corrections in this preview. Continue?',
      )
    )
      return;
    onEdit();
    if (source === 'file' && !file.current?.files?.length) {
      setError('Choose a roster HTML file first.');
      return;
    }
    if (source === 'url' && !url.trim()) {
      setError('Enter a roster URL first.');
      return;
    }
    const sequence = ++generation.current;
    const form = new FormData();
    form.set('name_order', order);
    if (source === 'file') form.set('roster_file', file.current!.files![0]!);
    else form.set('roster_url', url);
    setLoading(true);
    onBusyChange(true);
    setError('');
    try {
      const result = await previewRoster(form);
      if (sequence === generation.current) {
        setPreview(result);
        setCorrections({});
      }
    } catch (failure) {
      if (sequence === generation.current) setError(importProblem(failure).detail);
    } finally {
      if (sequence === generation.current) {
        setLoading(false);
        onBusyChange(false);
      }
    }
  }

  return (
    <>
      <section>
        <h2>Competition roster</h2>
        <div className="source-choices">
          {Object.entries({ file: 'Upload HTML', url: 'Supported URL', none: 'No roster' }).map(
            ([value, label]) => (
              <label key={value}>
                <input
                  type="radio"
                  checked={source === value}
                  disabled={busy}
                  onChange={() => {
                    setSource(value);
                    invalidate();
                  }}
                />{' '}
                {label}
              </label>
            ),
          )}
        </div>
        {source === 'file' && (
          <label>
            Roster HTML
            <input
              ref={file}
              name="roster_file"
              type="file"
              accept=".html,.htm,text/html"
              required
              disabled={busy}
              aria-invalid={visibleError ? true : undefined}
              aria-describedby={visibleError ? 'import-roster-error' : undefined}
              onChange={invalidate}
            />
          </label>
        )}
        {source === 'url' && (
          <label>
            Roster URL
            <input
              name="roster_url"
              type="url"
              placeholder="https://ergebnisse.leichtathletik.de/…"
              required
              disabled={busy}
              aria-invalid={visibleError ? true : undefined}
              aria-describedby={visibleError ? 'import-roster-error' : undefined}
              value={url}
              onChange={(event) => {
                setUrl(event.target.value);
                invalidate();
              }}
            />
          </label>
        )}
        <small>
          {source === 'none'
            ? 'Name detected people during review, then use face propagation to assign them to matching faces.'
            : 'Competitoroverview or Resultoverview from ergebnisse.leichtathletik.de.'}
        </small>
        {visibleError && (
          <p
            id="import-roster-error"
            className="error-text import-error"
            role="alert"
            tabIndex={-1}
            data-import-error={importError ? true : undefined}
          >
            {visibleError}
          </p>
        )}
        {source !== 'none' && (
          <>
            <label>
              Name order
              <select
                aria-label="Name order"
                aria-describedby="roster-name-order-help"
                name="name_order"
                value={order}
                disabled={busy}
                onChange={(event) => {
                  if (
                    Object.keys(corrections).length &&
                    !window.confirm(
                      'Changing name order clears the name corrections in this preview. Continue?',
                    )
                  )
                    return;
                  setOrder(event.target.value as Schema['NameOrder']);
                  invalidate();
                }}
              >
                {Object.entries(nameOrders).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <small id="roster-name-order-help">
                Auto uses commas, uppercase surnames, and surname initials such as Alex K. Other
                formats override automatic detection. Uppercase names are normalized; initials and
                existing mixed-case spellings are kept.
              </small>
            </label>
            <button type="button" disabled={busy || loading} onClick={() => void loadPreview()}>
              {loading ? 'Reading roster…' : 'Preview roster names'}
            </button>
          </>
        )}
      </section>
      {preview && source !== 'none' && (
        <section className="roster-preview-section">
          <input type="hidden" name="roster_digest" value={preview.digest} />
          <input
            type="hidden"
            name="roster_names"
            value={JSON.stringify(
              Object.entries(corrections).map(([index, name]) => ({ index: Number(index), name })),
            )}
          />
          <fieldset disabled={busy || loading}>
            <RosterNamePreview
              key={preview.digest}
              preview={preview}
              corrections={corrections}
              onChange={(index, name) =>
                setCorrections((previous) => ({ ...previous, [index]: name }))
              }
            />
          </fieldset>
        </section>
      )}
    </>
  );
}
