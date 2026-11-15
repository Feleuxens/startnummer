import type { BatchView } from '../../api/types';
import type { UnsavedChanges } from '../../hooks/useUnsavedChanges';
import type { RunAction } from '../../hooks/useAction';
import * as reviewApi from './api';
import { approved } from './model';

export default function ReviewHeader({
  view,
  busy,
  running,
  changes,
  action,
  onRefresh,
  onFacesCleared,
  onPreview,
}: {
  view: BatchView;
  busy: boolean;
  running: boolean;
  changes: UnsavedChanges;
  action: RunAction;
  onRefresh: () => Promise<BatchView>;
  onFacesCleared: () => void;
  onPreview: () => void;
}) {
  const batchId = view.batch.album.id;
  const photos = view.batch.photos;
  const latestJob = view.jobs[0];
  const approvedCount = photos.filter(approved).length;
  return (
    <>
      <div className="title-row">
        <div>
          <h1>{view.batch.album.name}</h1>
          <p>
            {photos.length} photos · {view.batch.roster.athletes?.length ?? 0} roster entries ·{' '}
            {approvedCount} approved
          </p>
        </div>
        <div className="actions">
          <button
            disabled={busy || running || changes.dirty.current}
            onClick={() =>
              void action(async () => {
                changes.requireSaved('Save current changes before analyzing again.');
                await reviewApi.analyzeBatch(batchId);
                await onRefresh();
              })
            }
          >
            {latestJob ? 'Analyze again' : 'Analyze batch'}
          </button>
          {running && (
            <button
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  await reviewApi.cancelAnalysis(batchId);
                  onFacesCleared();
                  await onRefresh();
                }, 'Analysis cancelled. Saved review work was kept.')
              }
            >
              Cancel analysis
            </button>
          )}
          <button
            disabled={busy || running}
            onClick={() =>
              void action(async () => {
                changes.requireSaved('Save the current caption before finishing the face session.');
                await reviewApi.finishFaceSession(batchId);
                await onRefresh();
              }, 'Review saved. Extracted face data has been discarded.')
            }
          >
            Save review and finish face session
          </button>
          <button
            className="primary"
            disabled={busy || running || !approvedCount}
            onClick={onPreview}
          >
            Preview Apply
          </button>
        </div>
      </div>

      {!latestJob && (
        <section className="import-preview">
          <h2>Ready to analyze</h2>
          <p>Meet: {view.batch.album.meet_name || 'Not supplied'}</p>
          <p>
            Roster sample:{' '}
            {view.batch.roster.athletes
              ?.slice(0, 3)
              .map((a) => `${a.bib || '—'} · ${a.name}`)
              .join(' / ')}
          </p>
        </section>
      )}
      {latestJob && (
        <div className="job-strip" role="status">
          <span className={`status ${latestJob.state}`}>{latestJob.state}</span>
          <span>
            {latestJob.phase} · {latestJob.completed} / {latestJob.total} photos
          </span>
          <progress
            value={latestJob.completed}
            max={latestJob.total || 1}
            aria-label="Analysis progress"
          />
          {latestJob.error && <span className="error-text">{latestJob.error}</span>}
        </div>
      )}
    </>
  );
}
