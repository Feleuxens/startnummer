import type { Preview } from '../../api/types';

export default function ApplyDialog({
  preview,
  busy,
  error,
  onClose,
  onConfirm,
}: {
  preview: Preview[];
  busy: boolean;
  error: string;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <dialog
      className="apply-dialog"
      aria-labelledby="apply-title"
      ref={(node) => {
        if (node && !node.open) node.showModal();
      }}
      onCancel={(event) => {
        if (busy) event.preventDefault();
        else onClose();
      }}
    >
      <h2 id="apply-title">Apply approved descriptions</h2>
      <p>{preview.length} mapped photos · description changes only</p>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {!preview.length && <p>No approved captions have a gallery destination.</p>}
      {preview.map((change) => (
        <div className="change-preview" key={change.photo_id}>
          <h3>{change.display_name}</h3>
          <div>
            <span>Current</span>
            <p>{change.change.expected ?? '(empty)'}</p>
          </div>
          <div>
            <span>Approved</span>
            <p>{change.change.replacement}</p>
          </div>
        </div>
      ))}
      <div className="actions">
        <button disabled={busy} onClick={() => onClose()}>
          Back to review
        </button>
        <button className="primary" disabled={busy || !preview.length} onClick={onConfirm}>
          {busy ? 'Applying…' : 'Apply to Chevereto'}
        </button>
      </div>
    </dialog>
  );
}
