import type { Schema } from '../api/types';

type Override = Schema['CaptionNameOverride'];
export type CaptionNameRow = Override & { key: string };

export const captionNameKey = (name: string) => name.trim().replace(/\s+/g, ' ').toLowerCase();
export const captionNameRow = (source_name = '', caption_name = ''): CaptionNameRow => ({
  key: crypto.randomUUID(),
  source_name,
  caption_name,
});
export const captionNameRows = (overrides: Override[] = []) =>
  overrides.map(({ source_name, caption_name }) => captionNameRow(source_name, caption_name));
export const captionNameOverrides = (rows: CaptionNameRow[]) =>
  rows.map(({ source_name, caption_name }) => ({ source_name, caption_name }));
export const hasDuplicateCaptionNames = (rows: CaptionNameRow[]) =>
  new Set(rows.map((row) => captionNameKey(row.source_name))).size !== rows.length;

export default function CaptionNameRows({
  rows,
  focusKey,
  onChange,
}: {
  rows: CaptionNameRow[];
  focusKey?: string;
  onChange: (rows: CaptionNameRow[]) => void;
}) {
  return (
    <ol className="caption-name-rules">
      {rows.map((row, index) => (
        <li key={row.key}>
          <label>
            Full source name
            <input
              aria-label={`Full source name ${index + 1}`}
              value={row.source_name}
              required
              maxLength={200}
              onChange={(event) =>
                onChange(
                  rows.map((current) =>
                    current.key === row.key
                      ? { ...current, source_name: event.target.value }
                      : current,
                  ),
                )
              }
            />
          </label>
          <label>
            Name in captions
            <input
              aria-label={`Name in captions ${index + 1}`}
              value={row.caption_name}
              data-caption-focus={row.key === focusKey ? true : undefined}
              required
              maxLength={200}
              onChange={(event) =>
                onChange(
                  rows.map((current) =>
                    current.key === row.key
                      ? { ...current, caption_name: event.target.value }
                      : current,
                  ),
                )
              }
            />
          </label>
          <button
            type="button"
            aria-label={`Remove name override ${index + 1}`}
            onClick={() => onChange(rows.filter((current) => current.key !== row.key))}
          >
            Remove
          </button>
        </li>
      ))}
    </ol>
  );
}
