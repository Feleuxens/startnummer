import { useState } from 'react';
import type { Schema } from '../../api/types';
import { matchesRosterQuery } from '../review/model';
import { nameOrders } from './model';

const pageSize = 20;

export default function RosterNamePreview({
  preview,
  corrections,
  onChange,
}: {
  preview: Schema['RosterPreview'];
  corrections: Record<number, string>;
  onChange: (index: number, name: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [onlyUncertain, setOnlyUncertain] = useState(false);
  const [page, setPage] = useState(0);
  const roster = preview.roster;
  const people = (roster.athletes ?? []).map((person, index) => ({ person, index }));
  // Filter by the original decision so editing never removes the focused input.
  const uncertain = (index: number) => roster.name_parsing?.[index]?.needs_review;
  const visible = people.filter(
    ({ person, index }) =>
      (matchesRosterQuery(person, query) ||
        matchesRosterQuery({ ...person, name: corrections[index] ?? person.name }, query)) &&
      (!onlyUncertain || uncertain(index)),
  );
  const current = Math.min(page, Math.max(0, Math.ceil(visible.length / pageSize) - 1));
  const rows = visible.slice(current * pageSize, (current + 1) * pageSize);
  return (
    <div className="roster-name-preview">
      <h3>Roster name preview</h3>
      <p>
        {people.length} entries ·{' '}
        {people.filter(({ index }) => uncertain(index) && !(index in corrections)).length} names to
        check
      </p>
      <p className="muted">
        {roster.name_order === 'auto'
          ? 'Auto detects each name separately. Ambiguous names assume surname first.'
          : `${nameOrders[roster.name_order ?? 'as_written']} is applied to this roster.`}{' '}
        Check the spelling and order below; corrections are saved when you import.
      </p>
      <label>
        Search roster names
        <input
          type="search"
          value={query}
          placeholder="Name, bib, or club"
          onChange={(event) => {
            setQuery(event.target.value);
            setPage(0);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') event.preventDefault();
          }}
        />
      </label>
      <label className="check-row">
        <input
          type="checkbox"
          checked={onlyUncertain}
          onChange={(event) => {
            setOnlyUncertain(event.target.checked);
            setPage(0);
          }}
        />
        Only uncertain automatic names
      </label>
      {!rows.length && <p>No roster entries match this filter.</p>}
      <ol className="roster-name-list">
        {rows.map(({ person, index }) => {
          const details = roster.name_parsing?.[index];
          return (
            <li key={index}>
              <div>
                <strong>{details?.source_name ?? person.name}</strong>
                <small>
                  {person.bib || 'No bib'} · {person.club || 'No club'}
                </small>
                <small>
                  {index in corrections
                    ? 'Corrected manually'
                    : `${uncertain(index) ? 'Assumed: ' : ''}${nameOrders[details?.order ?? 'as_written']}`}
                </small>
              </div>
              <label>
                Parsed name
                <input
                  aria-label={`Parsed name for roster person ${index + 1}`}
                  value={corrections[index] ?? person.name}
                  maxLength={200}
                  required
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') event.preventDefault();
                  }}
                  onChange={(event) => onChange(index, event.target.value)}
                />
              </label>
            </li>
          );
        })}
      </ol>
      <nav className="actions" aria-label="Roster name pages">
        <button type="button" disabled={current === 0} onClick={() => setPage(current - 1)}>
          Previous names
        </button>
        <span>
          {visible.length ? current * pageSize + 1 : 0}–
          {Math.min((current + 1) * pageSize, visible.length)} of {visible.length}
        </span>
        <button
          type="button"
          disabled={(current + 1) * pageSize >= visible.length}
          onClick={() => setPage(current + 1)}
        >
          Next names
        </button>
      </nav>
    </div>
  );
}
