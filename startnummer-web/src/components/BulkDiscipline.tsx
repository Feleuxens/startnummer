import { useState } from 'react';
import type { components } from '../api/schema';
import { message } from '../api/client';
import DisciplineSelect, { disciplineLabel } from './DisciplineSelect';

type Schema = components['schemas'];

export default function BulkDiscipline({
  photos,
  roster,
  disciplines,
  onClose,
  onPreview,
  onApply,
}: {
  photos: Schema['Photo'][];
  roster: Schema['EntryList'];
  disciplines: Schema['DisciplineOption'][];
  onClose: () => void;
  onPreview: (request: Schema['DisciplineAssignment']) => Promise<Schema['DisciplinePreview']>;
  onApply: (request: Schema['DisciplineAssignment']) => Promise<void>;
}) {
  const [discipline, setDiscipline] = useState<Schema['DisciplineOption']['value'] | null>(null);
  const [preview, setPreview] = useState<Schema['DisciplinePreview'] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const changed = preview?.photos.filter((photo) => photo.changed).length ?? 0;
  const label = (value: string | null) => {
    const option = disciplines.find((option) => option.value === value);
    return option ? disciplineLabel(option) : 'Undetermined';
  };
  const request = () => ({
    discipline: discipline!,
    photos: photos.map((photo) => ({ photo_id: photo.id, revision: photo.revision })),
  });
  async function submit(apply: boolean) {
    setBusy(true);
    setError('');
    try {
      if (apply)
        await onApply({
          ...request(),
          caption_names_revision: preview?.caption_names_revision,
          album_settings_revision: preview?.album_settings_revision,
        });
      else setPreview(await onPreview(request()));
    } catch (failure) {
      setError(message(failure));
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog
      className="apply-dialog discipline-dialog"
      aria-labelledby="discipline-title"
      ref={(node) => {
        if (node && !node.open) node.showModal();
      }}
      onCancel={(event) => {
        if (busy) event.preventDefault();
        else onClose();
      }}
    >
      <h2 id="discipline-title">Assign discipline to {photos.length} photos</h2>
      <p>
        Roster events are suggestions. You can choose any discipline. Manually edited captions are
        kept; changed photos will need approval again.
      </p>
      <label>
        Discipline for selected photos
        <DisciplineSelect
          value={discipline ?? ''}
          options={disciplines}
          photos={photos}
          roster={roster}
          disabled={busy}
          onChange={(value) => {
            setDiscipline(value);
            setPreview(null);
            setError('');
          }}
        />
      </label>
      <p>
        Choose No event to omit the discipline intentionally. Undetermined leaves it unresolved.
      </p>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="discipline-list">
        {preview ? (
          preview.photos.map((photo) => (
            <section className="change-preview" key={photo.photo_id}>
              <h3>{photo.display_name}</h3>
              <p>
                {label(photo.before_discipline)} → {label(preview.discipline)}
                {photo.manual_discipline && photo.changed && ' · replaces a manual discipline'}
              </p>
              {!photo.changed && <p>Already assigned. No change.</p>}
              {photo.caption_preserved ? (
                <>
                  <p>Manually edited caption kept</p>
                  <p>{photo.after_caption || '(empty)'}</p>
                </>
              ) : (
                <>
                  <div>
                    <span>Before</span>
                    <p>{photo.before_caption || '(empty)'}</p>
                  </div>
                  <div>
                    <span>After</span>
                    <p>{photo.after_caption || '(empty)'}</p>
                  </div>
                </>
              )}
            </section>
          ))
        ) : (
          <ul className="approval-list">
            {photos.map((photo) => (
              <li key={photo.id}>{photo.display_name}</li>
            ))}
          </ul>
        )}
      </div>
      <div className="actions">
        <button autoFocus disabled={busy} onClick={onClose}>
          Cancel
        </button>
        {preview ? (
          <button className="primary" disabled={busy || !changed} onClick={() => void submit(true)}>
            {busy ? 'Assigning…' : `Assign to ${changed} ${changed === 1 ? 'photo' : 'photos'}`}
          </button>
        ) : (
          <button
            className="primary"
            disabled={busy || !discipline}
            onClick={() => void submit(false)}
          >
            {busy ? 'Loading preview…' : 'Preview caption changes'}
          </button>
        )}
      </div>
    </dialog>
  );
}
