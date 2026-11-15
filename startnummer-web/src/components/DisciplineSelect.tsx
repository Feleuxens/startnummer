import type { components } from '../api/schema';

type Schema = components['schemas'];
type Discipline = Schema['DisciplineOption'];

export const disciplineLabel = (option: Discipline) =>
  option.value === 'no_event'
    ? 'No event (explicit decision)'
    : option.value === 'other'
      ? 'Other / unspecified'
      : `${option.de} / ${option.en}`;

export default function DisciplineSelect({
  value,
  options,
  photos,
  roster,
  disabled = false,
  onChange,
}: {
  value: string;
  options: Discipline[];
  photos: Schema['Photo'][];
  roster: Schema['EntryList'];
  disabled?: boolean;
  onChange: (value: Discipline['value'] | null) => void;
}) {
  const entered = photos.flatMap((photo) =>
    (photo.analysis?.record.subjects ?? []).flatMap(
      (subject) => subject.athlete?.value.entered_events ?? [],
    ),
  );
  const suggestions = new Set(
    entered.length
      ? entered
      : (roster.athletes ?? []).flatMap((athlete) => athlete.entered_events ?? []),
  );
  const suggested = options.filter((option) => suggestions.has(option.value));
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(event) =>
        onChange(options.find((option) => option.value === event.target.value)?.value ?? null)
      }
    >
      <option value="">Undetermined</option>
      {suggested.length > 0 && (
        <optgroup label={entered.length ? 'Entered by people in these photos' : 'In the roster'}>
          {suggested.map((option) => (
            <option key={option.value} value={option.value}>
              {disciplineLabel(option)}
            </option>
          ))}
        </optgroup>
      )}
      <optgroup label="All disciplines">
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {disciplineLabel(option)}
          </option>
        ))}
      </optgroup>
    </select>
  );
}
