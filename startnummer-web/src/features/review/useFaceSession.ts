import { useCallback, useEffect, useState } from 'react';
import type { FaceView, Schema } from '../../api/types';
import { emptyFaces } from './model';

const currentFaces = (faces: FaceView) =>
  faces.available && faces.expires_at != null && faces.expires_at * 1000 <= Date.now()
    ? emptyFaces
    : faces;

export function useFaceSession(onNotice: (message: string) => void) {
  const [faces, setFaces] = useState<FaceView>(emptyFaces);
  const [propagation, setPropagation] = useState<Schema['PropagationPreview'] | null>(null);
  const updateFaces = useCallback((next: FaceView) => setFaces(currentFaces(next)), []);

  useEffect(() => {
    if (!faces.available || !faces.expires_at) return;
    const timer = window.setTimeout(
      () => setFaces(emptyFaces),
      Math.max(0, faces.expires_at * 1000 - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [faces.expires_at, faces.available]);

  useEffect(() => {
    if (propagation && (!faces.available || propagation.face_session_id !== faces.session_id)) {
      setPropagation(null);
      onNotice('Face session ended. Saved names and captions are unchanged.');
    }
  }, [faces.available, faces.session_id, propagation, onNotice]);

  return { faces, setFaces: updateFaces, propagation, setPropagation };
}
