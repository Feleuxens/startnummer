import { useState } from 'react';
import type { components } from '../api/schema';

type Schema = components['schemas'];
type Candidate = Schema['PropagationCandidate'];
const targetKey = (candidate: Candidate) =>
  `${candidate.target.photo_id}:${candidate.target.subject}`;

export default function FacePropagation({
  preview,
  photos,
  busy,
  error,
  onClose,
  onApply,
  onReview,
}: {
  preview: Schema['PropagationPreview'];
  photos: Schema['Photo'][];
  busy: boolean;
  error: string;
  onClose: () => void;
  onApply: (targets: Schema['FaceTarget'][], acknowledgeWarnings: boolean) => Promise<void>;
  onReview: (target: Schema['FaceTarget']) => Promise<void>;
}) {
  const [selected, setSelected] = useState(
    () =>
      new Set(
        preview.candidates.filter((candidate) => candidate.state === 'eligible').map(targetKey),
      ),
  );
  const targets = preview.candidates.filter((candidate) => selected.has(targetKey(candidate)));
  const eligible = preview.candidates.filter((candidate) => candidate.state === 'eligible').length;
  const alreadyNamed = preview.candidates.filter(
    (candidate) => candidate.state === 'already_named',
  ).length;
  const blocked = preview.candidates.length - eligible - alreadyNamed;
  const [acknowledged, setAcknowledged] = useState(false);
  const needsAcknowledgement = Boolean(
    targets.length &&
    (preview.warnings.length || targets.some((candidate) => candidate.warnings.length)),
  );
  return (
    <dialog
      className="apply-dialog propagation-dialog"
      aria-labelledby="propagation-title"
      ref={(node) => {
        if (node && !node.open) node.showModal();
      }}
      onCancel={(event) => {
        if (busy) event.preventDefault();
        else onClose();
      }}
    >
      <h2 id="propagation-title">
        {eligible
          ? `Assign ${preview.athlete_name} to matching faces?`
          : `Matching faces for ${preview.athlete_name}`}
      </h2>
      <p>
        {eligible ? 'Check each match and deselect any wrong person. ' : 'No new names to assign. '}
        This covers the whole batch, including photos hidden by filters. Changed photos will need
        approval again.
      </p>
      {preview.candidates.length > 0 && (
        <p>
          {eligible} selectable · {alreadyNamed} already named · {blocked}{' '}
          {blocked === 1 ? 'needs' : 'need'} individual review
        </p>
      )}
      <p className="muted">
        Manual identity edits and conflicting roster bibs are excluded. Edited captions are kept.
      </p>
      {preview.warnings.length > 0 && (
        <ul className="bib-warnings">
          {preview.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {!preview.candidates.length && <p>No other matching faces were found in this session.</p>}
      <ul className="propagation-list">
        {preview.candidates.map((candidate) => {
          const photo = photos.find((photo) => photo.id === candidate.target.photo_id);
          const [x1 = 0, y1 = 0, x2 = 0, y2 = 0] = candidate.box;
          return (
            <li key={targetKey(candidate)}>
              <div className="propagation-image">
                <img
                  src={`${import.meta.env.PUBLIC_API_URL || ''}/api/photos/${candidate.target.photo_id}`}
                  alt={`Matching face in ${candidate.display_name}`}
                />
                <span
                  className="match-outline"
                  aria-hidden="true"
                  style={{
                    left: `${(100 * x1) / (photo?.width || 1)}%`,
                    top: `${(100 * y1) / (photo?.height || 1)}%`,
                    width: `${(100 * (x2 - x1)) / (photo?.width || 1)}%`,
                    height: `${(100 * (y2 - y1)) / (photo?.height || 1)}%`,
                  }}
                />
              </div>
              <div>
                {candidate.state === 'eligible' ? (
                  <label className="check-row propagation-choice">
                    <input
                      type="checkbox"
                      disabled={busy}
                      checked={selected.has(targetKey(candidate))}
                      onChange={(event) => {
                        const next = new Set(selected);
                        if (event.target.checked) next.add(targetKey(candidate));
                        else next.delete(targetKey(candidate));
                        setSelected(next);
                        setAcknowledged(false);
                      }}
                    />
                    {candidate.display_name} · person {candidate.target.subject + 1}
                  </label>
                ) : (
                  <>
                    <p className="propagation-filename">
                      {candidate.display_name} · person {candidate.target.subject + 1}
                    </p>
                    <strong>
                      {candidate.state === 'already_named'
                        ? 'Already named'
                        : 'Needs individual review'}
                    </strong>
                  </>
                )}
                <p>
                  {candidate.current_name || 'Name not matched'}
                  {candidate.state === 'eligible' && <> → {preview.athlete_name}</>}
                </p>
                {candidate.warnings.length > 0 && (
                  <ul className="bib-warnings">
                    {candidate.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                )}
                {candidate.state === 'blocked' && (
                  <>
                    <p className="muted">{candidate.reason}</p>
                    <button disabled={busy} onClick={() => void onReview(candidate.target)}>
                      Review this photo
                    </button>
                  </>
                )}
                {candidate.state === 'eligible' && (
                  <>
                    <h3>
                      {candidate.caption_preserved
                        ? 'Edited caption kept'
                        : 'Caption after assignment'}
                    </h3>
                    <p>{candidate.proposed_caption || '(empty)'}</p>
                    {!candidate.caption_preserved && candidate.before_caption && (
                      <p className="muted">Previously: {candidate.before_caption}</p>
                    )}
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {needsAcknowledgement && (
        <label className="check-row bib-confirmation">
          <input
            type="checkbox"
            disabled={busy}
            checked={acknowledged}
            onChange={(event) => setAcknowledged(event.target.checked)}
          />
          I checked the selected faces and proposed changes despite the warnings
        </label>
      )}
      <div className="actions">
        <button autoFocus disabled={busy} onClick={onClose}>
          Cancel
        </button>
        <button
          className="primary"
          disabled={busy || !targets.length || (needsAcknowledgement && !acknowledged)}
          onClick={() =>
            void onApply(
              targets.map((candidate) => candidate.target),
              acknowledged,
            )
          }
        >
          {busy
            ? 'Assigning name…'
            : !eligible
              ? 'Nothing to assign'
              : `Assign name to ${targets.length} selected ${targets.length === 1 ? 'photo' : 'photos'}`}
        </button>
      </div>
    </dialog>
  );
}
