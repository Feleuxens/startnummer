import type { Schema, Photo, Selection, FaceView } from '../../api/types';

export const photoUrl = (id: string) => `${import.meta.env.PUBLIC_API_URL || ''}/api/photos/${id}`;
export const approved = (photo: Photo) =>
  photo.approved_revision != null && photo.approved_revision === photo.revision;
export const canApprove = (photo: Photo) =>
  Boolean(
    photo.caption?.trim() &&
    photo.analysis &&
    (!photo.current_description ||
      photo.replace_existing ||
      photo.current_description === photo.caption),
  );
export const eligible = (photo: Photo) =>
  canApprove(photo) && (photo.analysis?.record.status === 'auto' || photo.conflicts_resolved);
export const selection = (photo: Photo): Selection => ({
  photo_id: photo.id,
  revision: photo.revision ?? 0,
});
export const matchesRosterQuery = (person: Schema['Athlete'], query: string) => {
  const text = [person.name, person.bib, person.club].filter(Boolean).join(' ').toLocaleLowerCase();
  return query
    .trim()
    .toLocaleLowerCase()
    .split(/\s+/)
    .every((term) => text.includes(term));
};
export const rosterPersonLabel = (person: Schema['Athlete']) =>
  [person.bib, person.name, person.club].filter(Boolean).join(' · ');
export const emptyFaces: FaceView = {
  available: false,
  session_id: null,
  photos: {},
  undo_count: 0,
  propagation_available: false,
};

export function filterPhotos(
  photos: Photo[],
  publications: Schema['Publication'][],
  filter: string,
) {
  const latestPublication = new Map(
    publications.map((operation) => [operation.photo_id, operation]),
  );
  const visible = photos.filter(
    (p) =>
      filter === 'all' ||
      (filter === 'unresolved' && p.analysis?.record.status !== 'auto' && !p.conflicts_resolved) ||
      (filter === 'approved' && approved(p)) ||
      (filter === 'unapproved' && !approved(p)) ||
      (filter === 'failed' && p.analysis?.record.status === 'failed') ||
      (filter === 'pending' && !p.analysis) ||
      (filter === 'undetermined' && p.analysis && !p.analysis.record.event.discipline) ||
      (filter === 'publishing-issues' &&
        !latestPublication.get(p.id)?.restored &&
        ['pending', 'conflict', 'failure'].includes(
          latestPublication.get(p.id)?.result.state ?? '',
        )) ||
      (filter === 'published' &&
        !latestPublication.get(p.id)?.restored &&
        ['applied', 'unchanged'].includes(latestPublication.get(p.id)?.result.state ?? '')),
  );
  return visible;
}

export function rangePhotoIds(visible: Photo[], from: string, to: string) {
  const start = visible.findIndex((photo) => photo.id === from);
  const end = visible.findIndex((photo) => photo.id === to);
  if (start < 0 || end < 0) return [];
  return visible
    .slice(Math.min(start, end), Math.max(start, end) + 1)
    .filter((photo) => photo.analysis)
    .map((photo) => photo.id);
}
