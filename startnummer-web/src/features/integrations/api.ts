import { api, unwrap } from '../../api/client';
import type { Schema } from '../../api/types';

const path = '/api/admin/integrations/chevereto';
export const getConnection = async () => unwrap(await api.GET(path));
export const saveConnection = async (body: Schema['CheveretoConnection']) =>
  unwrap(await api.PUT(path, { body }));
export const testConnection = async (body?: Schema['CheveretoConnection']) =>
  unwrap(await api.POST('/api/admin/integrations/chevereto/test', { body }));
export const confirmLegacy = async (revision: number) =>
  unwrap(
    await api.POST('/api/admin/integrations/chevereto/confirm-legacy', { body: { revision } }),
  );
