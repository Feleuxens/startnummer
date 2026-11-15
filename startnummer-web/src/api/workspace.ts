import { api, unwrap } from './client';

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
  unwrap(
    await api.POST('/api/batches', {
      body: form as never,
      bodySerializer: (body) => body as unknown as FormData,
    }),
  );
