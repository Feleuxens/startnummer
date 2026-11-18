import { useRef, useState } from 'react';
import RosterImport from '../features/import/RosterImport';

export default function ImportBatch({
  onImport,
  busy,
  gallery,
  canUseGallery,
}: {
  onImport: (data: FormData) => Promise<void>;
  busy: boolean;
  gallery: string;
  canUseGallery: boolean;
}) {
  const [photoSource, setPhotoSource] = useState(canUseGallery ? 'gallery' : 'files');
  const [rosterBusy, setRosterBusy] = useState(false);
  const [uploadNames, setUploadNames] = useState<string[]>([]);
  const importId = useRef(crypto.randomUUID());
  return (
    <>
      <div className="title-row">
        <div>
          <h1>New batch</h1>
          <p>Choose photos and, optionally, a competition roster.</p>
        </div>
      </div>
      <form
        className="import-form"
        onSubmit={(event) => {
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
          void onImport(form);
        }}
      >
        <section>
          <h2>Photos</h2>
          {canUseGallery && (
            <div className="source-choices">
              <label>
                <input
                  type="radio"
                  checked={photoSource === 'gallery'}
                  onChange={() => setPhotoSource('gallery')}
                />{' '}
                Chevereto album
              </label>
              <label>
                <input
                  type="radio"
                  checked={photoSource === 'files'}
                  onChange={() => setPhotoSource('files')}
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
              />
            </label>
          ) : (
            <label>
              Image files
              <input
                name="photos"
                type="file"
                accept="image/jpeg,image/mpo,.mpo,image/png,image/webp"
                multiple
                required
                onChange={(event) => {
                  const names = Array.from(event.target.files ?? []).map((file) => file.name);
                  setUploadNames(names);
                }}
              />
              <small>
                JPEG, PNG, or WebP. Select originals rather than generated face/annotation previews.
              </small>
              {uploadNames.length > 0 && <span>{uploadNames.length} photos selected</span>}
            </label>
          )}
        </section>
        <RosterImport busy={busy} onBusyChange={setRosterBusy} />
        <section className="import-details">
          <h2>Batch details</h2>
          <label>
            Album name
            <input name="name" placeholder="Saturday track meet" />
          </label>
          <label>
            Meet name
            <input
              name="meet_name"
              aria-label="Meet name"
              placeholder="Competition name used in captions"
            />
            <small>Separate from the discipline. Leave blank if unavailable.</small>
          </label>
        </section>
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
