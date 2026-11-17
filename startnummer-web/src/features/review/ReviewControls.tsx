import type { Photo, FaceView } from '../../api/types';
import type { PhotoSelection } from './usePhotoSelection';
import type { PhotoSort } from './model';

export default function ReviewControls({
  photos,
  faces,
  selection,
  busy,
  running,
  eligibleCount,
  onApproveAll,
  onUndo,
  onAssignDiscipline,
  onShowQueue,
  onSort,
}: {
  photos: Photo[];
  faces: FaceView;
  selection: PhotoSelection;
  busy: boolean;
  running: boolean;
  eligibleCount: number;
  onApproveAll: () => void;
  onUndo: () => void;
  onAssignDiscipline: () => void;
  onShowQueue: () => void;
  onSort: (order: PhotoSort) => void;
}) {
  const {
    filter,
    setFilter,
    selecting,
    toggleSelection,
    rangeStart,
    setRangeStart,
    rangeEnd,
    setRangeEnd,
    selectablePhotos,
    selectedPhotos,
    selectRange,
    clearSelection,
  } = selection;
  return (
    <>
      <div className="review-toolbar">
        <label>
          Show{' '}
          <select value={filter} onChange={(event) => setFilter(event.target.value)}>
            <option value="all">All photos</option>
            <option value="undetermined">Undetermined discipline</option>
            <option value="unresolved">Unresolved evidence</option>
            <option value="unapproved">Not approved</option>
            <option value="approved">Approved</option>
            <option value="failed">Analysis failed</option>
            <option value="pending">Not analyzed</option>
            <option value="publishing-issues">Publishing needs attention</option>
            <option value="published">Published</option>
          </select>
        </label>
        <label>
          Sort by{' '}
          <select
            value={selection.sort}
            disabled={busy}
            onChange={(event) => onSort(event.target.value as PhotoSort)}
          >
            <option value="name">Filename (A–Z)</option>
            <option value="modified">File modified date (oldest first)</option>
            <option value="taken">Date taken / EXIF (oldest first)</option>
            <option value="original">Import order</option>
          </select>
        </label>
        <button
          disabled={busy || running || !photos.some((photo) => photo.analysis)}
          aria-pressed={selecting}
          onClick={() => {
            toggleSelection();
            onShowQueue();
          }}
        >
          {selecting ? 'Done selecting' : 'Select photos'}
        </button>
        <button disabled={busy || running || !eligibleCount} onClick={onApproveAll}>
          Approve all eligible ({eligibleCount})…
        </button>
        {faces.available && faces.undo_id && faces.session_id && (
          <button disabled={busy || running} onClick={onUndo}>
            Undo last name assignment ({faces.undo_count})
          </button>
        )}
        <span className="muted">
          Face selection{' '}
          {faces.available
            ? 'available for this session'
            : 'unavailable · saved captions remain editable'}
        </span>
      </div>
      {selecting && (
        <section className="photo-selection" aria-label="Select photos for discipline">
          <div className="range-selection">
            <label>
              From photo
              <select
                value={rangeStart || selectablePhotos[0]?.id || ''}
                disabled={busy || running || !selectablePhotos.length}
                onChange={(event) => setRangeStart(event.target.value)}
              >
                {selectablePhotos.map((photo) => (
                  <option key={photo.id} value={photo.id}>
                    {photos.indexOf(photo) + 1}. {photo.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Through photo
              <select
                value={rangeEnd || selectablePhotos.at(-1)?.id || ''}
                disabled={busy || running || !selectablePhotos.length}
                onChange={(event) => setRangeEnd(event.target.value)}
              >
                {selectablePhotos.map((photo) => (
                  <option key={photo.id} value={photo.id}>
                    {photos.indexOf(photo) + 1}. {photo.display_name}
                  </option>
                ))}
              </select>
            </label>
            <button
              disabled={busy || running || !selectablePhotos.length}
              onClick={() =>
                selectRange(
                  rangeStart || selectablePhotos[0]!.id,
                  rangeEnd || selectablePhotos.at(-1)!.id,
                )
              }
            >
              Select range
            </button>
          </div>
          <div className="actions">
            <span role="status">{selectedPhotos.length} selected</span>
            <button disabled={busy || !selectedPhotos.length} onClick={clearSelection}>
              Clear selection
            </button>
            <button
              disabled={busy || running || !selectedPhotos.length}
              onClick={onAssignDiscipline}
            >
              Assign discipline…
            </button>
          </div>
          <p className="muted">
            Check photos individually or Shift-click to extend a selection. Ranges follow the
            current filter and sort order. Changing either clears the selection.
          </p>
        </section>
      )}
      {faces.available && !faces.propagation_available && (
        <p className="worker-notice" role="status">
          {faces.propagation_unavailable_reason ||
            'Name propagation is unavailable for this worker session. Restart the updated API and worker, then analyze a fresh batch. Keep this batch to preserve your review edits.'}{' '}
          Individual face naming remains available.
        </p>
      )}
    </>
  );
}
