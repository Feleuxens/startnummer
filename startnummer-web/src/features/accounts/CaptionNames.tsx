import { useEffect, useRef, useState } from 'react';
import { api, message, unwrap } from '../../api/client';
import type { Schema } from '../../api/types';

type Row = Schema['CaptionNameOverride'] & { key: string };
const rowsFrom = (settings: Schema['CaptionNames']) =>
  (settings.overrides ?? []).map((rule) => ({ ...rule, key: crypto.randomUUID() }));

export default function CaptionNames({
  onDirty,
  disabled,
}: {
  onDirty: (dirty: boolean) => void;
  disabled: boolean;
}) {
  const [saved, setSaved] = useState<Schema['CaptionNames'] | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const alive = useRef(true);
  const generation = useRef(0);

  function mark(value: boolean) {
    setDirty(value);
    onDirty(value);
    setNotice('');
  }

  async function load() {
    const sequence = ++generation.current;
    setBusy(true);
    setError('');
    try {
      const result = unwrap(await api.GET('/api/account/caption-names'));
      if (!alive.current || sequence !== generation.current) return;
      setSaved(result);
      setRows(rowsFrom(result));
      mark(false);
    } catch (failure) {
      if (alive.current && sequence === generation.current) setError(message(failure));
    } finally {
      if (alive.current && sequence === generation.current) setBusy(false);
    }
  }

  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
      generation.current += 1;
    };
  }, []);

  return (
    <section aria-labelledby="caption-names-title">
      <h2 id="caption-names-title">Caption name overrides</h2>
      <p>
        Use a different name in generated captions. Rules are private to your account and reusable
        across albums. Roster names, evidence, and matching stay unchanged.
      </p>
      <p>
        Match the full name, ignoring capitalization and extra spaces. Saved captions are kept until
        you refresh their suggestion or generate a new caption. Manually edited captions are
        preserved for comparison.
      </p>
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {saved ? (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            const keys = rows.map((row) =>
              row.source_name.trim().replace(/\s+/g, ' ').toLowerCase(),
            );
            if (new Set(keys).size !== keys.length) {
              setError('Each full source name can have only one override.');
              return;
            }
            setBusy(true);
            setError('');
            setNotice('');
            try {
              const result = unwrap(
                await api.PUT('/api/account/caption-names', {
                  body: {
                    revision: saved.revision,
                    overrides: rows.map(({ source_name, caption_name }) => ({
                      source_name,
                      caption_name,
                    })),
                  },
                }),
              );
              if (!alive.current) return;
              setSaved(result);
              setRows(rowsFrom(result));
              mark(false);
              setNotice('Caption name overrides saved. Existing captions were kept.');
            } catch (failure) {
              if (alive.current) setError(message(failure));
            } finally {
              if (alive.current) setBusy(false);
            }
          }}
        >
          <fieldset disabled={busy || disabled}>
            {!rows.length && <p>No caption name overrides configured.</p>}
            <ol className="caption-name-rules">
              {rows.map((row, index) => (
                <li key={row.key}>
                  <label>
                    Full source name
                    <input
                      aria-label={`Full source name ${index + 1}`}
                      value={row.source_name}
                      required
                      maxLength={200}
                      onChange={(event) => {
                        setRows((previous) =>
                          previous.map((current) =>
                            current.key === row.key
                              ? { ...current, source_name: event.target.value }
                              : current,
                          ),
                        );
                        mark(true);
                      }}
                    />
                  </label>
                  <label>
                    Name in captions
                    <input
                      aria-label={`Name in captions ${index + 1}`}
                      value={row.caption_name}
                      required
                      maxLength={200}
                      onChange={(event) => {
                        setRows((previous) =>
                          previous.map((current) =>
                            current.key === row.key
                              ? { ...current, caption_name: event.target.value }
                              : current,
                          ),
                        );
                        mark(true);
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    aria-label={`Remove name override ${index + 1}`}
                    onClick={() => {
                      setRows((previous) => previous.filter((current) => current.key !== row.key));
                      mark(true);
                    }}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ol>
            <div className="actions">
              <button
                type="button"
                disabled={rows.length >= 1000}
                onClick={() => {
                  setRows((previous) => [
                    ...previous,
                    { key: crypto.randomUUID(), source_name: '', caption_name: '' },
                  ]);
                  mark(true);
                }}
              >
                Add name override
              </button>
              <button className="primary" disabled={!dirty}>
                {busy ? 'Saving…' : 'Save name overrides'}
              </button>
              <button
                type="button"
                onClick={() => {
                  if (!dirty || window.confirm('Discard unsaved name overrides and reload?'))
                    void load();
                }}
              >
                Reload name overrides
              </button>
            </div>
          </fieldset>
        </form>
      ) : (
        <button disabled={busy || disabled} onClick={() => void load()}>
          {busy ? 'Loading name overrides…' : 'Load name overrides'}
        </button>
      )}
    </section>
  );
}
