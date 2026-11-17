import { useState } from 'react';
import type { Schema, SubjectEdit } from '../../api/types';
import { matchesRosterQuery, rosterPersonLabel } from './model';

export type SubjectDraft = Omit<SubjectEdit, 'subject' | 'face_session_id'>;

export default function SubjectEditor({
  subject,
  roster,
  draft,
  onChange,
  canFindMatches,
  onFindMatches,
  canRemove,
  onRemove,
}: {
  subject: Schema['Subject'];
  roster: Schema['EntryList'];
  draft: SubjectDraft;
  onChange: (draft: SubjectDraft) => void;
  canFindMatches: boolean;
  onFindMatches: () => void;
  canRemove: boolean;
  onRemove: () => void;
}) {
  const [query, setQuery] = useState('');
  const hasRoster = !!roster.athletes?.length;
  const people = (roster.athletes ?? []).filter(
    (person) => person.bib && matchesRosterQuery(person, query),
  );
  const chosen = draft.roster_bib
    ? roster.athletes?.find((person) => person.bib === draft.roster_bib)
    : undefined;
  return (
    <div className="subject-editor">
      <label>
        Correct bib
        <input
          value={'bib' in draft ? (draft.bib ?? '') : (subject.bibs?.[0]?.value ?? '')}
          onChange={(event) => onChange({ ...draft, bib: event.target.value })}
        />
      </label>
      {hasRoster && (
        <>
          <label>
            Search roster athletes
            <input
              type="search"
              value={query}
              placeholder="Name, bib, or club"
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') event.preventDefault();
              }}
            />
          </label>
          <label>
            Assign roster athlete
            <select
              value={draft.roster_bib ?? ''}
              onChange={(event) => {
                const { athlete_name: _name, club: _club, ...rest } = draft;
                onChange({ ...rest, roster_bib: event.target.value });
              }}
            >
              <option value="">Choose an athlete</option>
              {chosen && !people.includes(chosen) && (
                <optgroup label="Selected athlete">
                  <option value={chosen.bib ?? ''}>{rosterPersonLabel(chosen)}</option>
                </optgroup>
              )}
              {people.map((athlete) => (
                <option key={athlete.bib} value={athlete.bib ?? ''}>
                  {rosterPersonLabel(athlete)}
                </option>
              ))}
            </select>
          </label>
          {!people.length && <small>No roster athletes match this search.</small>}
        </>
      )}
      <label>
        {hasRoster ? 'Or enter a name' : 'Name'}
        <input
          value={draft.athlete_name ?? ''}
          placeholder={hasRoster ? 'Person absent from the roster' : 'Person’s name'}
          onChange={(event) => {
            const { roster_bib: _bib, ...rest } = draft;
            onChange({ ...rest, athlete_name: event.target.value, club: draft.club ?? '' });
          }}
        />
      </label>
      <label>
        Club (optional)
        <input
          value={draft.club ?? ''}
          onChange={(event) => onChange({ ...draft, club: event.target.value })}
        />
      </label>
      <small>
        {subject.added_manually
          ? 'Added manually from the roster. No detected face is linked to this entry.'
          : 'Saving names this occurrence. Find matching faces afterward to assign it elsewhere.'}
      </small>
      {!subject.added_manually && (
        <button type="button" disabled={!canFindMatches} onClick={onFindMatches}>
          Find matching faces…
        </button>
      )}
      {subject.added_manually && (
        <button type="button" className="danger-text" disabled={!canRemove} onClick={onRemove}>
          Remove added person
        </button>
      )}
    </div>
  );
}
