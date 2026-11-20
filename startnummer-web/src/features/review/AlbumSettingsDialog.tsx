import { useEffect, useRef, useState } from 'react';
import type { SubmitEvent } from 'react';
import { message } from '../../api/client';
import type { Schema } from '../../api/types';
import CaptionNameRows, {
  captionNameKey,
  captionNameOverrides,
  captionNameRow,
  captionNameRows,
  hasDuplicateCaptionNames,
} from '../../components/CaptionNameRows';
import { useUnsavedChanges } from '../../hooks/useUnsavedChanges';
import { getBatch, saveAlbumSettings } from './api';

function draftFrom(album: Schema['Album'], source?: string) {
  const rows = captionNameRows(album.caption_name_overrides);
  let focusKey: string | undefined;
  if (source) {
    let row = rows.find((rule) => captionNameKey(rule.source_name) === captionNameKey(source));
    if (!row && rows.length < 1000) {
      row = captionNameRow(source);
      rows.push(row);
    }
    focusKey = row?.key;
  }
  return {
    revision: album.settings_revision ?? 0,
    name: album.name,
    meet: album.meet_name ?? '',
    rows,
    focusKey,
  };
}

export default function AlbumSettingsDialog({
  album,
  sourceName,
  onClose,
  onSaved,
}: {
  album: Schema['Album'];
  sourceName?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const changes = useUnsavedChanges();
  const [draft, setDraft] = useState(() => draftFrom(album, sourceName));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    node.showModal();
    const replacement = node.querySelector<HTMLInputElement>('[data-caption-focus]');
    replacement?.focus();
    replacement?.select();
    return () => node.close();
  }, []);

  function edit(patch: Partial<typeof draft>) {
    setDraft((current) => ({ ...current, ...patch }));
    changes.setDirty(true);
  }

  function close() {
    if (!busy && changes.confirmLeave('Discard unsaved album settings?')) onClose();
  }

  async function reload() {
    if (!changes.confirmLeave('Discard unsaved album settings and reload?')) return;
    setBusy(true);
    setError('');
    try {
      setDraft(draftFrom((await getBatch(album.id)).batch.album));
      changes.setDirty(false);
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.name.trim()) {
      setError('Enter an album name.');
      return;
    }
    if (hasDuplicateCaptionNames(draft.rows)) {
      setError('Each full source name can have only one override.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await saveAlbumSettings(album.id, {
        revision: draft.revision,
        name: draft.name,
        meet_name: draft.meet,
        overrides: captionNameOverrides(draft.rows),
      });
      changes.setDirty(false);
      onSaved();
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      className="apply-dialog album-settings-dialog"
      aria-labelledby="album-settings-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <h2 id="album-settings-title">Album settings</h2>
      <form onSubmit={(event) => void submit(event)}>
        <fieldset disabled={busy}>
          <label>
            Album name
            <input
              required
              value={draft.name}
              onChange={(event) => edit({ name: event.target.value })}
            />
          </label>
          <label>
            Meet name
            <input value={draft.meet} onChange={(event) => edit({ meet: event.target.value })} />
            <small>Optional. Use the meet name you want to include in captions.</small>
          </label>
          <section aria-labelledby="album-caption-names-title">
            <h3 id="album-caption-names-title">Caption name overrides</h3>
            <p className="muted">
              Match the full source name. Rules here take priority over account rules for this
              album.
            </p>
            <CaptionNameRows
              rows={draft.rows}
              focusKey={draft.focusKey}
              onChange={(rows) => edit({ rows })}
            />
            <button
              type="button"
              disabled={draft.rows.length >= 1000}
              onClick={() => edit({ rows: [...draft.rows, captionNameRow()] })}
            >
              Add name override
            </button>
          </section>
          <p className="muted">Photos with changed suggestions need approval again.</p>
          {error && (
            <div>
              <p className="error-text" role="alert">
                {error}
              </p>
              <button type="button" onClick={() => void reload()}>
                Reload settings
              </button>
            </div>
          )}
          <div className="actions album-settings-actions">
            <button type="button" onClick={close}>
              Cancel
            </button>
            <button className="primary">{busy ? 'Working…' : 'Save album settings'}</button>
          </div>
        </fieldset>
      </form>
    </dialog>
  );
}
