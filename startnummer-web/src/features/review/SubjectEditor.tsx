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
  onOverrideCaptionName,
}: {
  subject: Schema['Subject'];
  roster: Schema['EntryList'];
  draft: SubjectDraft;
  onChange: (draft: SubjectDraft) => void;
  canFindMatches: boolean;
  onFindMatches: () => void;
  canRemove: boolean;
  onRemove: () => void;
  onOverrideCaptionName?: () => void;
}) {
  const [query, setQuery] = useState('');
  const hasRoster = !!roster.athletes?.length;
  const people = (roster.athletes ?? [])
    .map((person, index) => ({ person, index }))
    .filter(({ person }) => matchesRosterQuery(person, query));
  const chosenIndex =
    draft.roster_index ??
    (draft.roster_bib
      ? roster.athletes?.findIndex((person) => person.bib === draft.roster_bib)
      : undefined);
  const chosen = chosenIndex != null ? roster.athletes?.[chosenIndex] : undefined;
  const added = subject.added_manually ? subject.athlete?.value : undefined;
  const club = draft.club ?? (chosen ? '' : (added?.club ?? ''));
  return (
    <div className="subject-editor">
      <label>
        Correct bib
        <input
          value={
            'bib' in draft ? (draft.bib ?? '') : (added?.bib ?? subject.bibs?.[0]?.value ?? '')
          }
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
              value={chosenIndex ?? ''}
              onChange={(event) => {
                const {
                  athlete_name: _name,
                  club: _club,
                  roster_bib: _bib,
                  roster_index: _index,
                  ...rest
                } = draft;
                if (event.target.value === '') {
                  onChange(rest);
                  return;
                }
                const index = Number(event.target.value);
                const bib = roster.athletes?.[index]?.bib;
                onChange({ ...rest, roster_index: index, ...(bib ? { bib } : {}) });
              }}
            >
              <option value="">Choose an athlete</option>
              {chosen && !people.some(({ index }) => index === chosenIndex) && (
                <optgroup label="Selected athlete">
                  <option value={chosenIndex}>{rosterPersonLabel(chosen)}</option>
                </optgroup>
              )}
              {people.map(({ person, index }) => (
                <option key={index} value={index}>
                  {rosterPersonLabel(person)}
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
          value={draft.athlete_name ?? (chosen ? '' : (added?.name ?? ''))}
          placeholder={hasRoster ? 'Person absent from the roster' : 'Person’s name'}
          onChange={(event) => {
            const { roster_bib: _bib, roster_index: _index, ...rest } = draft;
            onChange({ ...rest, athlete_name: event.target.value, club });
          }}
        />
      </label>
      <label>
        Club (optional)
        <input
          value={club}
          onChange={(event) => onChange({ ...draft, club: event.target.value })}
        />
      </label>
      <small>
        {subject.added_manually
          ? 'No detected face is linked to this entry.'
          : 'Saving names this occurrence. Find matching faces afterward to assign it elsewhere.'}
      </small>
      {!subject.added_manually && (
        <button type="button" disabled={!canFindMatches} onClick={onFindMatches}>
          Find matching faces…
        </button>
      )}
      {onOverrideCaptionName && (
        <button type="button" onClick={onOverrideCaptionName}>
          Override name for this album…
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
