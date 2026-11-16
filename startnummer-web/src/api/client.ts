import createClient from 'openapi-fetch';
import type { paths } from './schema';

export const api = createClient<paths>({
  baseUrl: import.meta.env.PUBLIC_API_URL || '',
  credentials: 'same-origin',
  headers: { 'X-Requested-With': 'Startnummer' },
});

api.use({
  onResponse({ response, schemaPath, request }) {
    if (
      response.status === 401 &&
      !(schemaPath === '/api/session' && request.method === 'POST') &&
      !schemaPath.startsWith('/api/auth/')
    ) {
      window.dispatchEvent(new Event('startnummer:session-expired'));
    }
  },
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
