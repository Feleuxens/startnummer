import { api, unwrap } from './client';
import type { Schema } from './types';

type ImportProblem = Schema['ImportProblem'];

class ImportRequestError extends Error {
  constructor(readonly problem: ImportProblem) {
    super(problem.detail);
  }
}

export function importProblem(failure: unknown): ImportProblem {
  return failure instanceof ImportRequestError
    ? failure.problem
    : { detail: 'Could not reach Startnummer. Check your connection and try again.' };
}

function unwrapImport<T>(
  result: { data?: T; error?: unknown; response: Response },
  fallback: string,
  tooLarge: ImportProblem,
): T {
  if (result.data !== undefined) return result.data;
  if (result.response.status === 413) {
    throw new ImportRequestError(tooLarge);
  }
  const problem = result.error as Partial<ImportProblem> | undefined;
  if (result.response.status < 500 && typeof problem?.detail === 'string') {
    throw new ImportRequestError({
      detail: problem.detail,
      field: problem.field,
      files: problem.files,
    });
  }
  throw new ImportRequestError({ detail: fallback });
}

const rosterTooLarge: ImportProblem = {
  field: 'roster',
  detail: 'The roster upload is too large. Choose a smaller roster or No roster.',
};

export async function currentSession() {
  const result = await api.GET('/api/session');
  return result.data ?? null;
}

export const signIn = async (username: string, password: string) =>
  unwrap(await api.POST('/api/session', { body: { username, password } }));

export const signOut = async () => unwrap(await api.DELETE('/api/session'));
export const listAlbums = async () => unwrap(await api.GET('/api/batches'));
export const listDisciplines = async () => unwrap(await api.GET('/api/disciplines'));

export const importBatch = async (form: FormData) =>
  unwrapImport(
    await api.POST('/api/batches', {
      body: form as never,
      bodySerializer: (body) => body as unknown as FormData,
    }),
    'Could not import this batch. Try again. If it keeps happening, contact an administrator.',
    form.has('photos')
      ? {
          field: 'photos',
          detail:
            'The upload is too large. Select fewer photos or split them into smaller batches.',
        }
      : rosterTooLarge,
  );

export const previewRoster = async (form: FormData) =>
  unwrapImport(
    await api.POST('/api/roster/preview', {
      body: form as never,
      bodySerializer: (body) => body as unknown as FormData,
    }),
    'Could not read the roster. Try again or choose another roster.',
    rosterTooLarge,
  );

export const authStatus = async () => unwrap(await api.GET('/api/auth/status'));
export const register = async (body: { username: string; password: string; invitation?: string }) =>
  unwrap(await api.POST('/api/auth/register', { body }));
export const setup = async (body: { username: string; password: string; code: string }) =>
  unwrap(await api.POST('/api/auth/setup', { body }));
