import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import type { UnsavedChanges } from '../../hooks/useUnsavedChanges';
import type { RunAction } from '../../hooks/useAction';
import { useBatch } from './useBatch';
import { useFaceSession } from './useFaceSession';
import type { Schema, Photo, BatchView, Preview } from '../../api/types';
import * as reviewApi from './api';
import FacePropagation from '../../components/FacePropagation';
import BulkDiscipline from '../../components/BulkDiscipline';
import PhotoEditor from './PhotoEditor';
import ApprovalDialog from './ApprovalDialog';
import ApplyDialog from './ApplyDialog';
import ReviewHeader from './ReviewHeader';
import PublishingHistory from './PublishingHistory';
import PhotoViewer from './PhotoViewer';
import ReviewControls from './ReviewControls';
import PhotoQueue from './PhotoQueue';
import { usePhotoSelection } from './usePhotoSelection';
import { approved, eligible, selection, emptyFaces } from './model';

export type ReviewInput = { view: BatchView; generation: number };
export type ReviewStatus = { name: string; running: boolean };

type Props = {
  initial: ReviewInput;
  canPublish: boolean;
  messages: ReactNode;
  active: boolean;
  disciplines: Schema['DisciplineOption'][];
  changes: UnsavedChanges;
  busy: boolean;
  error: string;
  action: RunAction;
  setError: (error: string) => void;
  setNotice: (notice: string) => void;
  onStatus: (status: ReviewStatus) => void;
  onDelete: () => Promise<void>;
};

export default function BatchReview({
  initial,
  canPublish,
  messages,
  active,
  disciplines,
  changes,
  busy,
  error,
  action,
  setError,
  setNotice,
  onStatus,
  onDelete,
}: Props) {
  const { faces, setFaces, propagation, setPropagation } = useFaceSession(setNotice);
  const { view, running, refresh } = useBatch(initial.view, setFaces, setError);
  const [selectedId, setSelectedId] = useState<string | null>(
    initial.view.batch.photos[0]?.id ?? null,
  );
  const [subject, setSubject] = useState<number | null>(null);
  const [disciplinePhotos, setDisciplinePhotos] = useState<Photo[] | null>(null);
  const [preview, setPreview] = useState<Preview[] | null>(null);
  const [approvalPreview, setApprovalPreview] = useState<{
    batchId: string;
    albumName: string;
    photos: Photo[];
  } | null>(null);
  const [mobileDetail, setMobileDetail] = useState(false);
  const batchId = view.batch.album.id;

  useEffect(() => {
    onStatus({ name: view.batch.album.name, running });
  }, [view.batch.album.name, running, onStatus]);
  async function approvePhotos(photos: Photo[], targetBatchId = batchId) {
    if (!targetBatchId || !photos.length) return;
    await reviewApi.approvePhotos(targetBatchId, photos.map(selection));
    await refresh();
  }
  async function unapprovePhoto(photo: Photo) {
    if (!batchId) return;
    await reviewApi.unapprovePhoto(batchId, photo);
    await refresh();
  }
  async function approvePhoto(photo: Photo) {
    await reviewApi.approvePhoto(batchId, photo);
    await refresh();
  }
  function selectPhoto(photo: Photo) {
    if (busy) return;
    if (photo.id === selectedId) {
      setMobileDetail(true);
      return;
    }
    if (!changes.confirmLeave('Leave this photo without saving changes?')) return;
    changes.setDirty(false);
    setSelectedId(photo.id);
    setSubject(null);
    setMobileDetail(true);
    setError('');
    setNotice('');
  }
  async function confirmBulkApproval() {
    if (!approvalPreview) return;
    await approvePhotos(approvalPreview.photos, approvalPreview.batchId);
    const count = approvalPreview.photos.length;
    setApprovalPreview(null);
    setNotice(`${count} ${count === 1 ? 'caption' : 'captions'} approved in this album.`);
  }
  async function showPreview() {
    if (!batchId) return;
    changes.requireSaved('Save the current photo before previewing gallery changes.');
    setPreview(await reviewApi.previewApply(batchId));
  }
  async function applyPreview() {
    if (!batchId || !preview) return;
    let result: Schema['Publication'][];
    try {
      result = await reviewApi.applyDescriptions(
        batchId,
        preview.map((p) => ({ photo_id: p.photo_id, revision: p.revision })),
      );
    } finally {
      // An interrupted batch may already have applied some descriptions. Load
      // its durable outcomes even when the overall HTTP request failed.
      await refresh();
    }
    setPreview(null);
    const conflicts = result.filter((p) =>
      ['conflict', 'failure'].includes(p.result?.state ?? ''),
    ).length;
    setNotice(
      `${result.length - conflicts} captions applied or unchanged; ${conflicts} conflicts or failures.`,
    );
  }

  async function findMatches(photo: Photo, subject: number) {
    if (!batchId || !faces.session_id) return;
    changes.requireSaved('Save the name before finding matching faces.');
    setPropagation(
      await reviewApi.previewPropagation(
        batchId,
        { ...selection(photo), subject },
        faces.session_id,
      ),
    );
  }

  async function propagateNames(targets: Schema['FaceTarget'][], acknowledgeWarnings: boolean) {
    if (!batchId || !propagation) return;
    await action(
      async () => {
        await reviewApi.propagateNames(batchId, propagation, targets, acknowledgeWarnings);
        setPropagation(null);
        await refresh();
      },
      `Name assigned to ${targets.length} selected ${targets.length === 1 ? 'photo' : 'photos'}. Review before approving.`,
    );
  }

  const photos = view?.batch.photos ?? [];
  const photoSelection = usePhotoSelection(view);
  const { visible, selectedPhotos } = photoSelection;
  const selected = photos.find((p) => p.id === selectedId);
  const selectedPosition = photos.findIndex((p) => p.id === selectedId);
  const visibleIds = new Set(visible.map((p) => p.id));
  const previousPhoto = photos
    .slice(0, selectedPosition)
    .reverse()
    .find((p) => visibleIds.has(p.id));
  const nextPhoto = photos.slice(selectedPosition + 1).find((p) => visibleIds.has(p.id));
  const eligibleUnapproved = photos.filter((p) => eligible(p) && !approved(p));
  return (
    <>
      <div hidden={!active} className={`content ${mobileDetail ? 'detail-open' : ''}`}>
        {messages}
        <>
          <ReviewHeader
            canPublish={canPublish}
            view={view}
            busy={busy}
            running={running}
            changes={changes}
            action={action}
            onRefresh={refresh}
            onFacesCleared={() => setFaces(emptyFaces)}
            onPreview={() => void action(showPreview)}
          />
          <ReviewControls
            photos={photos}
            faces={faces}
            selection={photoSelection}
            busy={busy}
            running={running}
            eligibleCount={eligibleUnapproved.length}
            onShowQueue={() => setMobileDetail(false)}
            onApproveAll={() => {
              setError('');
              if (changes.dirty.current) {
                setError('Save the current photo’s changes before approving captions in bulk.');
                return;
              }
              setApprovalPreview({
                batchId,
                albumName: view.batch.album.name,
                photos: eligibleUnapproved,
              });
            }}
            onUndo={() =>
              void action(async () => {
                changes.requireSaved('Save current edits before undoing a name assignment.');
                if (
                  !window.confirm(
                    `Undo the last name assignment in ${faces.undo_count} photos? Approvals will be removed. Photos edited afterward cannot be undone.`,
                  )
                )
                  return false;
                await reviewApi.undoPropagation(batchId, faces.session_id!, faces.undo_id!);
                await refresh();
              }, 'Last name assignment undone. Review the affected captions before approving.')
            }
            onAssignDiscipline={() => {
              setError('');
              if (changes.dirty.current) {
                setError('Save the current photo’s changes before assigning a discipline.');
                return;
              }
              setDisciplinePhotos(selectedPhotos);
            }}
          />
          <div className={`review-grid ${mobileDetail ? 'show-detail' : ''}`}>
            <PhotoQueue
              selection={photoSelection}
              selectedId={selectedId}
              busy={busy}
              running={running}
              onSelectPhoto={selectPhoto}
            />

            {selected && (
              <section className="photo-detail" aria-label="Selected photo">
                <button className="mobile-back" onClick={() => setMobileDetail(false)}>
                  ← Back to photos
                </button>
                <div className="photo-heading">
                  <h2>{selected.display_name}</h2>
                </div>
                <PhotoViewer
                  selected={selected}
                  faces={faces}
                  subject={subject}
                  busy={busy}
                  running={running}
                  previousPhoto={previousPhoto}
                  nextPhoto={nextPhoto}
                  position={selectedPosition}
                  total={photos.length}
                  onNavigate={selectPhoto}
                  onSelectSubject={(index) => {
                    if (changes.dirty.current) {
                      setError('Save current changes before selecting another face.');
                      return;
                    }
                    setSubject(index);
                  }}
                />
                <PhotoEditor
                  key={`${selected.id}:${selected.revision}`}
                  photo={selected}
                  roster={view.batch.roster}
                  disciplines={disciplines}
                  subject={subject}
                  setSubject={setSubject}
                  faces={faces}
                  busy={busy || running}
                  onDirty={(value) => {
                    changes.setDirty(value);
                  }}
                  onSave={(patch) =>
                    action(async () => {
                      await reviewApi.savePhoto(batchId, selected.id, patch);
                      changes.setDirty(false);
                      await refresh();
                    }, `Changes saved for ${selected.display_name}.`)
                  }
                  onApprove={() =>
                    action(
                      () => approvePhoto(selected),
                      `Caption approved for ${selected.display_name}.`,
                    )
                  }
                  onUnapprove={() =>
                    action(
                      () => unapprovePhoto(selected),
                      `Approval removed for ${selected.display_name}.`,
                    )
                  }
                  onFindMatches={(index) => action(() => findMatches(selected, index))}
                  onAddPerson={(rosterIndex) =>
                    action(async () => {
                      changes.requireSaved('Save current edits before adding a person.');
                      const photo = await reviewApi.addPerson(batchId, selected, rosterIndex);
                      await refresh();
                      setSubject((photo.analysis?.record.subjects.length ?? 1) - 1);
                    }, 'Person added. Review the generated caption before approving.')
                  }
                  onRemovePerson={(index) =>
                    action(async () => {
                      changes.requireSaved('Save current edits before removing a person.');
                      if (
                        !window.confirm(
                          'Remove this added person from the photo and regenerate the caption suggestion?',
                        )
                      )
                        return false;
                      await reviewApi.removePerson(batchId, selected, index);
                      setSubject(null);
                      await refresh();
                    }, 'Added person removed. Review the caption before approving.')
                  }
                />
              </section>
            )}
          </div>
          {canPublish && (
            <PublishingHistory
              view={view}
              busy={busy}
              running={running}
              changes={changes}
              action={action}
              onRefresh={refresh}
              onSelectPhoto={selectPhoto}
              onNotice={setNotice}
            />
          )}

          <button
            className="danger-text"
            disabled={busy || running}
            onClick={() =>
              void action(async () => {
                if (
                  !window.confirm(
                    `Delete this saved batch and its ${photos.length} local photos? Chevereto images will remain.`,
                  )
                )
                  return;
                await reviewApi.deleteBatch(batchId);
                changes.setDirty(false);
                setFaces(emptyFaces);
                await onDelete();
              })
            }
          >
            Delete saved batch…
          </button>
        </>
      </div>
      {active && (
        <>
          {disciplinePhotos && view && (
            <BulkDiscipline
              photos={disciplinePhotos}
              roster={view.batch.roster}
              disciplines={disciplines}
              onClose={() => setDisciplinePhotos(null)}
              onPreview={(request) => reviewApi.previewDiscipline(batchId, request)}
              onApply={async (request) => {
                const updated = await reviewApi.assignDiscipline(batchId, request);
                await refresh();
                setDisciplinePhotos(null);
                photoSelection.reset();
                const changed = updated.filter((photo) =>
                  request.photos.some(
                    (selection) =>
                      selection.photo_id === photo.id && selection.revision !== photo.revision,
                  ),
                ).length;
                setNotice(
                  `Discipline assigned to ${changed} photos. Review changed captions before approving.`,
                );
              }}
            />
          )}
          {propagation && (
            <FacePropagation
              preview={propagation}
              photos={photos}
              busy={busy}
              error={error}
              onClose={() => setPropagation(null)}
              onApply={propagateNames}
              onReview={async (target) => {
                if (!batchId) return;
                await action(async () => {
                  const data = await refresh();
                  const photo = data.batch.photos.find((photo) => photo.id === target.photo_id);
                  if (!photo) throw new Error('This photo is no longer available.');
                  setPropagation(null);
                  setSelectedId(photo.id);
                  setSubject(photo.revision === target.revision ? target.subject : null);
                  setMobileDetail(true);
                });
              }}
            />
          )}
          {approvalPreview && (
            <ApprovalDialog
              approvalPreview={approvalPreview}
              busy={busy}
              error={error}
              onClose={() => setApprovalPreview(null)}
              onConfirm={() => void action(confirmBulkApproval)}
            />
          )}
          {preview && (
            <ApplyDialog
              preview={preview}
              busy={busy}
              error={error}
              onClose={() => setPreview(null)}
              onConfirm={() => void action(applyPreview)}
            />
          )}
        </>
      )}
    </>
  );
}
