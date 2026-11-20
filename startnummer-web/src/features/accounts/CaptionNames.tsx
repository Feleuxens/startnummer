import { useEffect, useRef, useState } from 'react';
import { api, message, unwrap } from '../../api/client';
import type { Schema } from '../../api/types';
import CaptionNameRows, {
  captionNameOverrides,
  captionNameRow,
  captionNameRows,
  hasDuplicateCaptionNames,
} from '../../components/CaptionNameRows';
import type { CaptionNameRow } from '../../components/CaptionNameRows';

export default function CaptionNames({
  onDirty,
  disabled,
}: {
  onDirty: (dirty: boolean) => void;
  disabled: boolean;
}) {
  const [saved, setSaved] = useState<Schema['CaptionNames'] | null>(null);
  const [rows, setRows] = useState<CaptionNameRow[]>([]);
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
      setRows(captionNameRows(result.overrides));
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
            if (hasDuplicateCaptionNames(rows)) {
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
                    overrides: captionNameOverrides(rows),
                  },
                }),
              );
              if (!alive.current) return;
              setSaved(result);
              setRows(captionNameRows(result.overrides));
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
            <CaptionNameRows
              rows={rows}
              onChange={(next) => {
                setRows(next);
                mark(true);
              }}
            />
            <div className="actions">
              <button
                type="button"
                disabled={rows.length >= 1000}
                onClick={() => {
                  setRows((previous) => [...previous, captionNameRow()]);
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
