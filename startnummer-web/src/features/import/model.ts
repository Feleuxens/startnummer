import type { Schema } from '../../api/types';

export const nameOrders: Record<Schema['NameOrder'], string> = {
  auto: 'Auto',
  surname_first: 'Surname first',
  given_first: 'Given name first',
  as_written: 'Keep source order',
};
