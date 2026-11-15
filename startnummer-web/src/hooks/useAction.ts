import { useCallback, useState } from 'react';
import { message } from '../api/client';

export type RunAction = (task: () => Promise<unknown>, success?: string) => Promise<void>;

export function useAction() {
  const [pending, setPending] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const action: RunAction = useCallback(async (task, success = '') => {
    setPending((count) => count + 1);
    setError('');
    setNotice('');
    try {
      const result = await task();
      if (success && result !== false) setNotice(success);
    } catch (failure) {
      setError(message(failure));
    } finally {
      setPending((count) => count - 1);
    }
  }, []);
  return { busy: pending > 0, error, notice, setError, setNotice, action };
}
