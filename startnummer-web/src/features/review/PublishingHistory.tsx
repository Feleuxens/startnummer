import type { BatchView, Photo } from '../../api/types';
import type { UnsavedChanges } from '../../hooks/useUnsavedChanges';
import type { RunAction } from '../../hooks/useAction';
import * as reviewApi from './api';

export default function PublishingHistory({
  view,
  busy,
  running,
  changes,
  action,
  onRefresh,
  onSelectPhoto,
  onNotice,
}: {
  view: BatchView;
  busy: boolean;
  running: boolean;
  changes: UnsavedChanges;
  action: RunAction;
  onRefresh: () => Promise<BatchView>;
  onSelectPhoto: (photo: Photo) => void;
  onNotice: (message: string) => void;
}) {
  const batchId = view.batch.album.id;
  const photos = view.batch.photos;
  return (
    <section className="publishing-history">
      <h2>Publishing history</h2>
      {!view.publications.length ? (
        <p className="muted">No descriptions have been applied from this batch.</p>
      ) : (
        view.publications.map((operation) => (
          <div className="history-row" key={operation.id}>
            <span>{photos.find((p) => p.id === operation.photo_id)?.display_name}</span>
            <span className={operation.result?.state === 'conflict' ? 'error-text' : ''}>
              {operation.restored ? 'restored' : operation.result?.state}
            </span>
            {operation.result?.error && <span>{operation.result.error}</span>}
            {operation.result?.state === 'conflict' && (
              <span>Live description: {operation.result.live_value ?? '(empty)'}</span>
            )}
            {!operation.restored &&
              ['pending', 'failure', 'conflict'].includes(operation.result.state) && (
                <>
                  <button
                    disabled={busy || running}
                    onClick={() =>
                      void action(async () => {
                        changes.requireSaved('Save current edits before checking the gallery.');
                        const result = await reviewApi.reconcilePublication(batchId, operation.id);
                        await onRefresh();
                        onNotice(
                          result.result.state === 'unchanged'
                            ? 'Gallery change confirmed. No description was written.'
                            : result.result.error ||
                                'Gallery differs from this operation. Load its live description to review.',
                        );
                      })
                    }
                  >
                    Check gallery outcome
                  </button>
                  <button
                    disabled={busy || running}
                    onClick={() =>
                      void action(async () => {
                        changes.requireSaved(
                          'Save current edits before loading the gallery description.',
                        );
                        const photo = photos.find((photo) => photo.id === operation.photo_id);
                        if (!photo) return;
                        await reviewApi.refreshDescription(batchId, photo);
                        await onRefresh();
                        onSelectPhoto(photo);
                      }, 'Live description loaded. Review and approve the replacement again.')
                    }
                  >
                    Load live description for review
                  </button>
                </>
              )}
            {!operation.restored &&
              ['applied', 'unchanged'].includes(operation.result?.state ?? '') && (
                <button
                  disabled={busy}
                  onClick={() =>
                    void action(async () => {
                      changes.requireSaved('Save current edits before restoring a description.');
                      if (
                        !window.confirm(
                          'Restore the previous gallery description? This succeeds only if it has not changed since Apply.',
                        )
                      )
                        return false;
                      const result = await reviewApi.restoreDescription(batchId, operation.id);
                      if (['conflict', 'failure'].includes(result.state))
                        throw new Error(
                          result.error || 'Gallery description changed; restore was not applied.',
                        );
                      await onRefresh();
                    }, 'Previous description restored.')
                  }
                >
                  Restore previous description
                </button>
              )}
          </div>
        ))
      )}
    </section>
  );
}
