import { useEffect, useRef, useState } from 'react';
import type { SubmitEvent } from 'react';
import type { Schema } from '../api/types';
import { importBatch, importProblem } from '../api/workspace';
import RosterImport from '../features/import/RosterImport';
import type { RunAction } from '../hooks/useAction';

const imageFormats = 'image/jpeg,image/mpo,.mpo,image/png,image/webp';

export default function ImportBatch({
  action,
  onImported,
  busy,
  gallery,
  canUseGallery,
}: {
  action: RunAction;
  onImported: (id: string) => Promise<void>;
  busy: boolean;
  gallery: string;
  canUseGallery: boolean;
}) {
  const [photoSource, setPhotoSource] = useState(canUseGallery ? 'gallery' : 'files');
  const [rosterBusy, setRosterBusy] = useState(false);
  const [uploadCount, setUploadCount] = useState(0);
  const [problem, setProblem] = useState<Schema['ImportProblem'] | null>(null);
  const importForm = useRef<HTMLFormElement>(null);
  const focusProblem = useRef(false);
  const photoInput = useRef<HTMLInputElement>(null);
  const replacementInput = useRef<HTMLInputElement>(null);
  const replacementIndex = useRef<number | null>(null);
  const importId = useRef(crypto.randomUUID());
  const photoProblem = problem?.field === 'photos' || problem?.field === 'album' ? problem : null;

  useEffect(() => {
    if (problem && focusProblem.current) {
      focusProblem.current = false;
      importForm.current?.querySelector<HTMLElement>('[data-import-error]')?.focus();
    }
  }, [problem]);

  function clearPhotoProblem() {
    setProblem((current) =>
      current?.field === 'photos' || current?.field === 'album' ? null : current,
    );
  }

  function changePhotoSource(source: 'gallery' | 'files') {
    setPhotoSource(source);
    setUploadCount(0);
    clearPhotoProblem();
  }

  function reviseFile(index: number, replacement?: File) {
    const input = photoInput.current;
    if (!input) return;
    const next = new DataTransfer();
    for (const [position, file] of Array.from(input.files ?? []).entries()) {
      if (position !== index) next.items.add(file);
      else if (replacement) next.items.add(replacement);
    }
    input.files = next.files;
    setUploadCount(next.files.length);
    setProblem((current) => {
      if (current?.field !== 'photos') return current;
      const remaining = (current.files ?? [])
        .filter((file) => file.index !== index)
        .map((file) =>
          !replacement && file.index != null && file.index > index
            ? { ...file, index: file.index - 1 }
            : file,
        );
      return remaining.length ? { ...current, files: remaining } : null;
    });
    input.focus();
  }

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    form.set('import_id', importId.current);
    if (photoSource === 'files') {
      const modified = form.getAll('photos').map((photo) => {
        if (!(photo instanceof File)) return null;
        const date = new Date(photo.lastModified);
        return Number.isFinite(date.getTime()) ? date.toISOString() : null;
      });
      form.set('photo_modified', JSON.stringify(modified));
    }
    setProblem(null);
    void action(async () => {
      let batch;
      try {
        batch = await importBatch(form);
      } catch (failure) {
        focusProblem.current = true;
        setProblem(importProblem(failure));
        return;
      }
      await onImported(batch.album.id);
    });
  }

  return (
    <>
      <div className="title-row">
        <div>
          <h1>New batch</h1>
          <p>Choose photos and, optionally, a competition roster.</p>
        </div>
      </div>
      <form ref={importForm} className="import-form" onSubmit={submit}>
        <section>
          <h2>Photos</h2>
          {canUseGallery && (
            <div className="source-choices">
              <label>
                <input
                  type="radio"
                  checked={photoSource === 'gallery'}
                  disabled={busy}
                  onChange={() => changePhotoSource('gallery')}
                />{' '}
                Chevereto album
              </label>
              <label>
                <input
                  type="radio"
                  checked={photoSource === 'files'}
                  disabled={busy}
                  onChange={() => changePhotoSource('files')}
                />{' '}
                Upload images
              </label>
            </div>
          )}
          {photoSource === 'gallery' ? (
            <label>
              Album URL
              <input
                name="gallery_url"
                type="url"
                placeholder={
                  gallery ? `${gallery}/album/…` : 'Configure a gallery to import an album'
                }
                required
                disabled={busy}
                aria-invalid={photoProblem ? true : undefined}
                aria-describedby={photoProblem ? 'import-photo-error' : undefined}
                onChange={clearPhotoProblem}
              />
            </label>
          ) : (
            <label>
              Image files
              <input
                ref={photoInput}
                name="photos"
                type="file"
                accept={imageFormats}
                multiple
                required
                disabled={busy}
                aria-invalid={photoProblem ? true : undefined}
                aria-describedby={photoProblem ? 'import-photo-error' : undefined}
                onChange={(event) => {
                  setUploadCount(event.target.files?.length ?? 0);
                  clearPhotoProblem();
                }}
              />
              <small>
                JPEG, PNG, or WebP. Select originals rather than generated face/annotation previews.
              </small>
              {uploadCount > 0 && (
                <span>
                  {uploadCount} {uploadCount === 1 ? 'photo' : 'photos'} selected
                </span>
              )}
            </label>
          )}
          {photoProblem && (
            <>
              <p
                id="import-photo-error"
                className="error-text import-error"
                role="alert"
                tabIndex={-1}
                data-import-error
              >
                {photoProblem.detail}
              </p>
              {Boolean(photoProblem.files?.length) && (
                <ul className="import-file-errors" aria-label="Files that could not be imported">
                  {photoProblem.files?.map((file, position) => {
                    const index = photoSource === 'files' ? file.index : null;
                    return (
                      <li key={index ?? position}>
                        <div>
                          <strong>{file.name}</strong>
                          <p>{file.detail}</p>
                        </div>
                        {index != null && (
                          <div className="import-file-actions">
                            <button
                              type="button"
                              disabled={busy}
                              aria-label={`Replace ${file.name}`}
                              onClick={() => {
                                replacementIndex.current = index;
                                replacementInput.current?.click();
                              }}
                            >
                              Replace
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              aria-label={`Remove ${file.name}`}
                              onClick={() => reviseFile(index)}
                            >
                              Remove
                            </button>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
          <input
            ref={replacementInput}
            type="file"
            hidden
            accept={imageFormats}
            aria-label="Replacement image"
            onChange={(event) => {
              const index = replacementIndex.current;
              const replacement = event.currentTarget.files?.[0];
              replacementIndex.current = null;
              event.currentTarget.value = '';
              if (index != null && replacement) reviseFile(index, replacement);
            }}
          />
        </section>
        <RosterImport
          busy={busy}
          onBusyChange={setRosterBusy}
          importError={problem?.field === 'roster' ? problem.detail : undefined}
          onEdit={() => setProblem((current) => (current?.field === 'roster' ? null : current))}
        />
        <section className="import-details">
          <h2>Batch details</h2>
          <label>
            Album name
            <input name="name" placeholder="Saturday track meet" disabled={busy} />
          </label>
          <label>
            Meet name
            <input
              name="meet_name"
              aria-label="Meet name"
              placeholder="Competition name used in captions"
              disabled={busy}
            />
            <small>Separate from the discipline. Leave blank if unavailable.</small>
          </label>
        </section>
        {problem && !problem.field && (
          <p
            className="error-text import-submit-error"
            role="alert"
            tabIndex={-1}
            data-import-error
          >
            {problem.detail}
          </p>
        )}
        <div className="import-footer">
          <p>Import saves the inputs. You can check the photo count before starting analysis.</p>
          <button className="primary" disabled={busy || rosterBusy}>
            {busy ? 'Importing…' : 'Import and preview'}
          </button>
        </div>
      </form>
    </>
  );
}
