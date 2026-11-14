import createClient from 'openapi-fetch';
import type { paths } from './schema';

export const api = createClient<paths>({
  baseUrl: import.meta.env.PUBLIC_API_URL || '',
  credentials: 'same-origin',
  headers: { 'X-Requested-With': 'Startnummer' },
});

export function message(error: unknown): string {
  if (error && typeof error === 'object' && 'detail' in error) {
    const detail = (error as { detail: unknown }).detail;
    return typeof detail === 'string' ? detail : 'Check the supplied values and try again.';
  }
  return error instanceof Error ? error.message : 'The request failed. Try again.';
}

export function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error || result.data === undefined) throw new Error(message(result.error));
  return result.data;
}
