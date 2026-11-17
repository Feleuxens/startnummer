import { useRef, useState } from 'react';
import type { BatchView } from '../../api/types';
import { filterPhotos, rangePhotoIds, sortPhotos } from './model';
import type { PhotoSort } from './model';

export function usePhotoSelection(view: BatchView) {
  const [filter, updateFilter] = useState('all');
  const [sort, updateSort] = useState<PhotoSort>('name');
  const [selecting, setSelecting] = useState(false);
  const [checkedPhotos, setCheckedPhotos] = useState<Set<string>>(new Set());
  const [rangeStart, setRangeStart] = useState('');
  const [rangeEnd, setRangeEnd] = useState('');
  const anchor = useRef<string | null>(null);
  const orderedPhotos = sortPhotos(view.batch.photos, sort);
  const visible = filterPhotos(orderedPhotos, view.publications, filter);
  const selectablePhotos = visible.filter((photo) => photo.analysis);
  const selectedPhotos = selectablePhotos.filter((photo) => checkedPhotos.has(photo.id));

  function clearSelection() {
    setCheckedPhotos(new Set());
    anchor.current = null;
  }
  function reset() {
    clearSelection();
    setRangeStart('');
    setRangeEnd('');
  }
  function setFilter(next: string) {
    updateFilter(next);
    reset();
  }
  function setSort(next: PhotoSort) {
    updateSort(next);
    reset();
  }
  function toggleSelection() {
    setSelecting(!selecting);
    clearSelection();
  }
  function selectRange(from: string, to: string, add = false, checked = true) {
    const ids = rangePhotoIds(visible, from, to);
    if (!ids.length) return;
    setCheckedPhotos((previous) => {
      const next = new Set(add ? previous : []);
      for (const id of ids) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }
  function togglePhoto(id: string, checked: boolean, shift: boolean) {
    if (shift && anchor.current) selectRange(anchor.current, id, true, checked);
    else
      setCheckedPhotos((previous) => {
        const next = new Set(previous);
        if (checked) next.add(id);
        else next.delete(id);
        return next;
      });
    anchor.current = id;
  }

  return {
    filter,
    setFilter,
    sort,
    setSort,
    orderedPhotos,
    selecting,
    toggleSelection,
    visible,
    selectablePhotos,
    selectedPhotos,
    checkedPhotos,
    rangeStart,
    setRangeStart,
    rangeEnd,
    setRangeEnd,
    clearSelection,
    reset,
    selectRange,
    togglePhoto,
  };
}

export type PhotoSelection = ReturnType<typeof usePhotoSelection>;
