import { api, unwrap } from '../../api/client';
import type { Edit, Photo, Schema, Selection } from '../../api/types';

export const getBatch = async (batchId: string) =>
  unwrap(await api.GET('/api/batches/{batch_id}', { params: { path: { batch_id: batchId } } }));

export const getFaces = async (batchId: string) =>
  unwrap(
    await api.GET('/api/batches/{batch_id}/faces', { params: { path: { batch_id: batchId } } }),
  );

export const readPhotoDates = async (batchId: string) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/photo-dates', {
      params: { path: { batch_id: batchId } },
    }),
  );

export async function getReview(batchId: string) {
  const [view, faces] = await Promise.all([getBatch(batchId), getFaces(batchId)]);
  return { view, faces };
}

export const analyzeBatch = async (batchId: string) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/analysis', { params: { path: { batch_id: batchId } } }),
  );

export const cancelAnalysis = async (batchId: string) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/analysis/cancel', {
      params: { path: { batch_id: batchId } },
    }),
  );

export const finishFaceSession = async (batchId: string) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/finish', { params: { path: { batch_id: batchId } } }),
  );

export const deleteBatch = async (batchId: string) =>
  unwrap(await api.DELETE('/api/batches/{batch_id}', { params: { path: { batch_id: batchId } } }));

export const savePhoto = async (batchId: string, photoId: string, edit: Edit) =>
  unwrap(
    await api.PATCH('/api/batches/{batch_id}/photos/{photo_id}', {
      params: { path: { batch_id: batchId, photo_id: photoId } },
      body: edit,
    }),
  );

export const approvePhotos = async (batchId: string, photos: Selection[]) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/approve', {
      params: { path: { batch_id: batchId } },
      body: { photos },
    }),
  );

export const approvePhoto = async (batchId: string, photo: Photo) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/photos/{photo_id}/approve', {
      params: { path: { batch_id: batchId, photo_id: photo.id } },
      body: { revision: photo.revision },
    }),
  );

export const unapprovePhoto = async (batchId: string, photo: Photo) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/photos/{photo_id}/unapprove', {
      params: { path: { batch_id: batchId, photo_id: photo.id } },
      body: { revision: photo.revision },
    }),
  );

export const addPerson = async (batchId: string, photo: Photo, rosterIndex: number) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/photos/{photo_id}/subjects', {
      params: { path: { batch_id: batchId, photo_id: photo.id } },
      body: { revision: photo.revision, roster_index: rosterIndex },
    }),
  );

export const removePerson = async (batchId: string, photo: Photo, subject: number) =>
  unwrap(
    await api.DELETE('/api/batches/{batch_id}/photos/{photo_id}/subjects/{subject_index}', {
      params: { path: { batch_id: batchId, photo_id: photo.id, subject_index: subject } },
      body: { revision: photo.revision },
    }),
  );

export const previewDiscipline = async (batchId: string, request: Schema['DisciplineAssignment']) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/discipline-preview', {
      params: { path: { batch_id: batchId } },
      body: request,
    }),
  );

export const assignDiscipline = async (batchId: string, request: Schema['DisciplineAssignment']) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/discipline', {
      params: { path: { batch_id: batchId } },
      body: request,
    }),
  );

export const previewPropagation = async (
  batchId: string,
  source: Schema['FaceTarget'],
  sessionId: string,
) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/face-propagation/preview', {
      params: { path: { batch_id: batchId } },
      body: { source, face_session_id: sessionId },
    }),
  );

export const propagateNames = async (
  batchId: string,
  preview: Schema['PropagationPreview'],
  targets: Schema['FaceTarget'][],
  acknowledgeWarnings: boolean,
) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/face-propagation', {
      params: { path: { batch_id: batchId } },
      body: {
        source: preview.source,
        face_session_id: preview.face_session_id,
        targets,
        acknowledge_unsupported_bibs: acknowledgeWarnings,
        acknowledge_tentative_names: acknowledgeWarnings,
      },
    }),
  );

export const undoPropagation = async (batchId: string, sessionId: string, undoId: string) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/face-propagation/undo', {
      params: { path: { batch_id: batchId } },
      body: { face_session_id: sessionId, undo_id: undoId },
    }),
  );

export const previewApply = async (batchId: string) =>
  unwrap(
    await api.GET('/api/batches/{batch_id}/apply-preview', {
      params: { path: { batch_id: batchId } },
    }),
  );

export const applyDescriptions = async (batchId: string, photos: Selection[]) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/apply', {
      params: { path: { batch_id: batchId } },
      body: { photos },
    }),
  );

export const reconcilePublication = async (batchId: string, operationId: string) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/publications/{operation_id}/reconcile', {
      params: { path: { batch_id: batchId, operation_id: operationId } },
    }),
  );

export const refreshDescription = async (batchId: string, photo: Photo) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/photos/{photo_id}/refresh-description', {
      params: { path: { batch_id: batchId, photo_id: photo.id } },
      body: { revision: photo.revision },
    }),
  );

export const restoreDescription = async (batchId: string, operationId: string) =>
  unwrap(
    await api.POST('/api/batches/{batch_id}/publications/{operation_id}/restore', {
      params: { path: { batch_id: batchId, operation_id: operationId } },
    }),
  );
