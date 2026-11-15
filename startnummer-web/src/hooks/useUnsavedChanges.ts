import { useEffect, useMemo, useRef } from 'react';

export function useUnsavedChanges() {
  const dirty = useRef(false);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty.current) event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, []);

  return useMemo(
    () => ({
      dirty,
      setDirty(value: boolean) {
        dirty.current = value;
      },
      confirmLeave(prompt: string) {
        return !dirty.current || window.confirm(prompt);
      },
      requireSaved(message: string) {
        if (dirty.current) throw new Error(message);
      },
    }),
    [],
  );
}

export type UnsavedChanges = ReturnType<typeof useUnsavedChanges>;
