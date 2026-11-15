import type { Photo } from '../../api/types';

export type ApprovalPreview = { batchId: string; albumName: string; photos: Photo[] };
export default function ApprovalDialog({
  approvalPreview,
  busy,
  error,
  onClose,
  onConfirm,
}: {
  approvalPreview: ApprovalPreview;
  busy: boolean;
  error: string;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <dialog
      className="apply-dialog"
      aria-labelledby="approval-title"
      ref={(node) => {
        if (node && !node.open) node.showModal();
      }}
      onCancel={(event) => {
        if (busy) event.preventDefault();
        else onClose();
      }}
    >
      <h2 id="approval-title">Approve all eligible captions?</h2>
      <p>
        {approvalPreview.photos.length} {approvalPreview.photos.length === 1 ? 'photo' : 'photos'}{' '}
        in {approvalPreview.albumName}. This covers the whole album, including photos hidden by the
        current filter.
      </p>
      <p>
        Blank captions, unresolved photos, and already approved captions are excluded. Applying
        descriptions to Chevereto is a separate action.
      </p>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <ul className="approval-list">
        {approvalPreview.photos.map((photo) => (
          <li key={photo.id}>
            <h3>{photo.display_name}</h3>
            <p>{photo.caption}</p>
          </li>
        ))}
      </ul>
      <div className="actions">
        <button autoFocus disabled={busy} onClick={() => onClose()}>
          Cancel
        </button>
        <button className="primary" disabled={busy} onClick={onConfirm}>
          {busy
            ? 'Approving…'
            : `Approve ${approvalPreview.photos.length} ${approvalPreview.photos.length === 1 ? 'caption' : 'captions'}`}
        </button>
      </div>
    </dialog>
  );
}
