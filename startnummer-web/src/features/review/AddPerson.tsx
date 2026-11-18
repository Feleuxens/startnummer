import { useState } from 'react';
import type { KeyboardEvent } from 'react';
import type { Schema } from '../../api/types';
import type { PersonToAdd } from './api';
import { matchesRosterQuery, rosterPersonLabel } from './model';

function preventCaptionSubmit(event: KeyboardEvent<HTMLDivElement>) {
  if (event.key === 'Enter' && event.target instanceof HTMLInputElement) event.preventDefault();
}

export default function AddPerson({
  roster,
  empty,
  dirty,
  onAdd,
}: {
  roster: Schema['EntryList'];
  empty: boolean;
  dirty: boolean;
  onAdd: (person: PersonToAdd) => Promise<void>;
}) {
  const [query, setQuery] = useState('');
  const [rosterIndex, setRosterIndex] = useState('');
  const [name, setName] = useState('');
  const [bib, setBib] = useState('');
  const [club, setClub] = useState('');
  const athletes = roster.athletes ?? [];
  const choices = athletes
    .map((person, index) => ({ person, index }))
    .filter(({ person }) => matchesRosterQuery(person, query));

  return (
    <>
      {athletes.length > 0 && (
        <details className="add-person" open={empty}>
          <summary>Add person from roster</summary>
          <div className="subject-editor" onKeyDown={preventCaptionSubmit}>
            <label>
              Find roster person
              <input
                value={query}
                placeholder="Name, bib, or club"
                onChange={(event) => {
                  setQuery(event.target.value);
                  setRosterIndex('');
                }}
              />
            </label>
            <label>
              Person to add
              <select value={rosterIndex} onChange={(event) => setRosterIndex(event.target.value)}>
                <option value="">Choose a person</option>
                {choices.map(({ person, index }) => (
                  <option value={index} key={index}>
                    {rosterPersonLabel(person)}
                  </option>
                ))}
              </select>
            </label>
            {!choices.length && <small>No roster entries match this search.</small>}
            {dirty && <small>Save current edits before adding a person.</small>}
            <button
              type="button"
              disabled={dirty || rosterIndex === ''}
              onClick={() => void onAdd({ roster_index: Number(rosterIndex) })}
            >
              Add to this photo
            </button>
          </div>
        </details>
      )}
      <details className="add-person" open={empty && !athletes.length}>
        <summary>Add person manually</summary>
        <div className="subject-editor" onKeyDown={preventCaptionSubmit}>
          <label>
            Person’s name
            <input value={name} maxLength={200} onChange={(event) => setName(event.target.value)} />
          </label>
          <label>
            Person’s bib (optional)
            <input value={bib} maxLength={64} onChange={(event) => setBib(event.target.value)} />
          </label>
          <label>
            Person’s club (optional)
            <input value={club} maxLength={200} onChange={(event) => setClub(event.target.value)} />
          </label>
          {dirty && <small>Save current edits before adding a person.</small>}
          <button
            type="button"
            disabled={dirty || !name.trim()}
            onClick={() => void onAdd({ person: { name, bib, club } })}
          >
            Add to this photo
          </button>
        </div>
      </details>
    </>
  );
}
