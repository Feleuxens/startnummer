import type { Photo } from '../../api/types';
import type { PhotoSelection } from './usePhotoSelection';
import { approved, photoUrl } from './model';

export default function PhotoQueue({
  selection,
  selectedId,
  busy,
  running,
  onSelectPhoto,
}: {
  selection: PhotoSelection;
  selectedId: string | null;
  busy: boolean;
  running: boolean;
  onSelectPhoto: (photo: Photo) => void;
}) {
  const { visible, checkedPhotos, selecting, togglePhoto } = selection;
  return (
    <section className="contact-sheet" aria-label="Photo queue">
      {visible.map((photo) => (
        <div
          key={photo.id}
          className={`photo-choice ${checkedPhotos.has(photo.id) ? 'checked' : ''}`}
        >
          {selecting && (
            <label className="photo-check">
              <input
                type="checkbox"
                aria-label={`Select ${photo.display_name}`}
                disabled={busy || running || !photo.analysis}
                checked={checkedPhotos.has(photo.id)}
                onChange={(event) =>
                  togglePhoto(
                    photo.id,
                    event.target.checked,
                    (event.nativeEvent as MouseEvent).shiftKey,
                  )
                }
              />
              Select
            </label>
          )}
          <button
            disabled={busy}
            className={`photo-tile ${photo.id === selectedId ? 'selected' : ''}`}
            onClick={() => onSelectPhoto(photo)}
          >
            <img src={photoUrl(photo.id)} alt={photo.display_name} loading="lazy" />
            <span>{photo.display_name}</span>
            <small className={approved(photo) ? 'positive' : ''}>
              {approved(photo)
                ? 'Approved'
                : photo.analysis?.record.status?.replaceAll('_', ' ') || 'Not analyzed'}
            </small>
          </button>
        </div>
      ))}
      {!visible.length && <p className="empty">No photos match this filter.</p>}
    </section>
  );
}
