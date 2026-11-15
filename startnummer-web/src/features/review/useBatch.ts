import { useCallback, useEffect, useRef, useState } from 'react';
import type { BatchView, FaceView } from '../../api/types';
import { message } from '../../api/client';
import { getReview } from './api';

export function useBatch(
  initial: BatchView,
  onFaces: (faces: FaceView) => void,
  onError: (message: string) => void,
) {
  const [view, setView] = useState(initial);
  const batchId = initial.batch.album.id;
  const running = view.jobs.some((job) => ['queued', 'running'].includes(job.state ?? ''));
  const active = useRef(true);
  const request = useRef(0);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      request.current += 1;
    };
  }, []);

  const refresh = useCallback(async () => {
    const sequence = ++request.current;
    const result = await getReview(batchId);
    if (active.current && sequence === request.current) {
      setView(result.view);
      onFaces(result.faces);
    }
    return result.view;
  }, [batchId, onFaces]);

  useEffect(() => {
    void refresh().catch((failure) => {
      if (active.current) onError(message(failure));
    });
  }, [refresh, onError]);

  useEffect(() => {
    if (!running) return;
    let stopped = false;
    let pending = false;
    const timer = window.setInterval(async () => {
      if (pending) return;
      pending = true;
      try {
        await refresh();
      } catch (failure) {
        if (!stopped) onError(message(failure));
      } finally {
        pending = false;
      }
    }, 1800);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [running, refresh, onError]);

  return { view, running, refresh };
}
