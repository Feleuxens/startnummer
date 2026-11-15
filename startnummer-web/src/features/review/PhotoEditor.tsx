import { useEffect, useState } from 'react';
import type { SubmitEvent } from 'react';
import type { Schema, Photo, Edit, FaceView } from '../../api/types';
import DisciplineSelect from '../../components/DisciplineSelect';
import { matchesRosterQuery, rosterPersonLabel, approved, eligible } from './model';

export default function PhotoEditor({
  photo,
  roster,
  disciplines,
  subject,
  setSubject,
  faces,
  busy,
  onDirty,
  onSave,
  onApprove,
  onUnapprove,
  onFindMatches,
  onAddPerson,
  onRemovePerson,
}: {
  photo: Photo;
  roster: Schema['EntryList'];
  disciplines: Schema['DisciplineOption'][];
  subject: number | null;
  setSubject: (subject: number | null) => void;
  faces: FaceView;
  busy: boolean;
  onDirty: (dirty: boolean) => void;
  onSave: (patch: Edit) => Promise<void>;
  onApprove: () => Promise<void>;
  onUnapprove: () => Promise<void>;
  onFindMatches: (subject: number) => Promise<void>;
  onAddPerson: (rosterIndex: number) => Promise<void>;
  onRemovePerson: (subject: number) => Promise<void>;
}) {
  const [caption, setCaption] = useState(photo.caption ?? '');
  const [replace, setReplace] = useState(photo.replace_existing ?? false);
  const [resolved, setResolved] = useState(photo.conflicts_resolved ?? false);
  const [patch, setPatch] = useState<Partial<Edit>>({});
  const [dirty, setDirty] = useState(false);
  const [rosterQuery, setRosterQuery] = useState('');
  const [rosterIndex, setRosterIndex] = useState('');
  const [athleteQuery, setAthleteQuery] = useState('');
  useEffect(() => setAthleteQuery(''), [subject]);
  const peopleToAdd = (roster.athletes ?? [])
    .map((person, index) => ({ person, index }))
    .filter(({ person }) => matchesRosterQuery(person, rosterQuery));
  const peopleToAssign = (roster.athletes ?? []).filter(
    (person) => person.bib && matchesRosterQuery(person, athleteQuery),
  );
  const chosenAthlete = patch.roster_bib
    ? roster.athletes?.find((person) => person.bib === patch.roster_bib)
    : undefined;
  const record = photo.analysis?.record;
  const subjects = record?.subjects ?? [];
  const mark = () => {
    setDirty(true);
    onDirty(true);
  };
  const update = (values: Partial<Edit>) => {
    setPatch((previous) => ({ ...previous, ...values }));
    mark();
  };
  const discipline = record?.event.discipline?.value ?? '';
  const currentSubject = subject == null ? null : subjects[subject];

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const body: Edit = {
      revision: photo.revision ?? 0,
      replace_existing: replace,
      conflicts_resolved: resolved,
      ...patch,
    };
    if (caption !== (photo.caption ?? '')) body.caption = caption;
    if (
      subject != null &&
      ('athlete_name' in patch || 'roster_bib' in patch || 'bib' in patch || 'club' in patch)
    ) {
      body.subject = subject;
      if (
        faces.available &&
        faces.session_id &&
        faces.photos[photo.id]?.some((face) => face.subject === subject)
      )
        body.face_session_id = faces.session_id;
    }
    void onSave(body);
  }

  return (
    <form className="editor" onSubmit={submit}>
      <fieldset className="editor-fields" disabled={busy}>
        {record?.failure_reason && <p className="error-text">{record.failure_reason}</p>}
        <div className="caption-compare">
          <div>
            <h3>Current gallery description</h3>
            <p>
              {photo.destination ? photo.current_description || 'Empty' : 'No gallery destination'}
            </p>
          </div>
          <label>
            Reviewed caption
            <textarea
              value={caption}
              rows={4}
              onChange={(event) => {
                setCaption(event.target.value);
                mark();
              }}
            />
          </label>
        </div>
        {photo.proposal && photo.proposal !== caption && (
          <details>
            <summary>Analysis suggestion</summary>
            <p>{photo.proposal}</p>
          </details>
        )}
        {photo.current_description && (
          <label className="check-row">
            <input
              type="checkbox"
              checked={replace}
              onChange={(event) => {
                setReplace(event.target.checked);
                mark();
              }}
            />
            Replace the existing gallery description
          </label>
        )}
        <section className="evidence">
          <h3>Subjects and evidence</h3>
          {!subjects.length && (
            <p className="muted">
              {record
                ? 'No subjects detected. Add someone from the roster to generate a caption.'
                : 'Add someone from the roster, or analyze the batch to detect subjects.'}
            </p>
          )}
          <details className="add-person" open={!subjects.length}>
            <summary>Add person from roster</summary>
            <div className="subject-editor">
              <label>
                Find roster person
                <input
                  value={rosterQuery}
                  placeholder="Name, bib, or club"
                  onChange={(event) => {
                    setRosterQuery(event.target.value);
                    setRosterIndex('');
                  }}
                />
              </label>
              <label>
                Person to add
                <select
                  value={rosterIndex}
                  onChange={(event) => setRosterIndex(event.target.value)}
                >
                  <option value="">Choose a person</option>
                  {peopleToAdd.map(({ person, index }) => (
                    <option value={index} key={index}>
                      {rosterPersonLabel(person)}
                    </option>
                  ))}
                </select>
              </label>
              {!peopleToAdd.length && <small>No roster entries match this search.</small>}
              <small>
                Adds this person to this photo and generates a caption suggestion. Edited captions
                are kept.
              </small>
              {dirty && <small>Save current edits before adding a person.</small>}
              <button
                type="button"
                disabled={busy || dirty || rosterIndex === ''}
                onClick={() => void onAddPerson(Number(rosterIndex))}
              >
                Add to this photo
              </button>
            </div>
          </details>
          {subjects.map((item, index) => (
            <button
              type="button"
              className={`subject-row ${subject === index ? 'selected' : ''}`}
              key={index}
              onClick={() => {
                if (
                  dirty &&
                  ('athlete_name' in patch ||
                    'roster_bib' in patch ||
                    'bib' in patch ||
                    'club' in patch)
                )
                  return;
                setSubject(subject === index ? null : index);
              }}
            >
              <span>{index + 1}</span>
              <div>
                <strong>{item.athlete?.value.name || 'Name not matched'}</strong>
                <small>
                  {item.bibs
                    ?.map(
                      (bib) =>
                        `${bib.value} · ${Math.round(bib.confidence * 100)}% · ${bib.source}`,
                    )
                    .join(' / ') || 'No bib read'}
                </small>
                {item.athlete && (
                  <small>
                    {Math.round(item.athlete.confidence * 100)}% · {item.athlete.source} ·{' '}
                    {item.athlete.note}
                  </small>
                )}
              </div>
            </button>
          ))}
          {currentSubject && (
            <div className="subject-editor">
              <label>
                Correct bib
                <input
                  defaultValue={currentSubject.bibs?.[0]?.value ?? ''}
                  key={`bib-${subject}`}
                  onChange={(event) => update({ bib: event.target.value })}
                />
              </label>
              <label>
                Search roster athletes
                <input
                  type="search"
                  value={athleteQuery}
                  placeholder="Name, bib, or club"
                  onChange={(event) => setAthleteQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') event.preventDefault();
                  }}
                />
              </label>
              <label>
                Assign roster athlete
                <select
                  value={patch.roster_bib ?? ''}
                  onChange={(event) => {
                    const { athlete_name: _name, club: _club, ...rest } = patch;
                    setPatch({ ...rest, roster_bib: event.target.value });
                    mark();
                  }}
                >
                  <option value="">Choose an athlete</option>
                  {chosenAthlete && !peopleToAssign.includes(chosenAthlete) && (
                    <optgroup label="Selected athlete">
                      <option value={chosenAthlete.bib ?? ''}>
                        {rosterPersonLabel(chosenAthlete)}
                      </option>
                    </optgroup>
                  )}
                  {peopleToAssign.map((athlete) => (
                    <option key={athlete.bib} value={athlete.bib ?? ''}>
                      {rosterPersonLabel(athlete)}
                    </option>
                  ))}
                </select>
              </label>
              {!peopleToAssign.length && <small>No roster athletes match this search.</small>}
              <label>
                Or enter a name
                <input
                  value={patch.athlete_name ?? ''}
                  placeholder="Person absent from the roster"
                  onChange={(event) => {
                    const { roster_bib: _bib, ...rest } = patch;
                    setPatch({ ...rest, athlete_name: event.target.value });
                    mark();
                  }}
                />
              </label>
              <label>
                Club (optional)
                <input
                  value={patch.club ?? ''}
                  onChange={(event) => update({ club: event.target.value })}
                />
              </label>
              <small>
                {currentSubject.added_manually
                  ? 'Added manually from the roster. No detected face is linked to this entry.'
                  : 'Saving names this occurrence. Find matching faces afterward to assign it elsewhere.'}
              </small>
              {subject != null && !currentSubject.added_manually && (
                <button
                  type="button"
                  disabled={
                    busy ||
                    dirty ||
                    !faces.available ||
                    !faces.propagation_available ||
                    currentSubject.athlete?.source !== 'manual' ||
                    !faces.photos[photo.id]?.some((face) => face.subject === subject)
                  }
                  onClick={() => void onFindMatches(subject)}
                >
                  Find matching faces…
                </button>
              )}
              {subject != null && currentSubject.added_manually && (
                <button
                  type="button"
                  className="danger-text"
                  disabled={busy || dirty}
                  onClick={() => void onRemovePerson(subject)}
                >
                  Remove added person
                </button>
              )}
            </div>
          )}
        </section>
        {record && (
          <label>
            Discipline
            <DisciplineSelect
              value={'discipline' in patch ? (patch.discipline ?? '') : discipline}
              options={disciplines}
              photos={[photo]}
              roster={roster}
              disabled={busy}
              onChange={(value) => update({ discipline: value })}
            />
            {record.event.discipline?.note && (
              <small>
                {record.event.discipline.source} · {record.event.discipline.note}
              </small>
            )}
          </label>
        )}
        {record && (
          <label className="check-row">
            <input
              type="checkbox"
              checked={resolved}
              onChange={(event) => {
                setResolved(event.target.checked);
                mark();
              }}
            />
            I reviewed and resolved uncertain evidence in this photo
          </label>
        )}
        <div className="editor-actions">
          <button type="submit" disabled={busy || !dirty}>
            {busy ? 'Working…' : 'Save caption and corrections'}
          </button>
          {approved(photo) ? (
            <button type="button" disabled={busy} onClick={() => void onUnapprove()}>
              Unapprove this photo
            </button>
          ) : (
            <button
              type="button"
              className="primary"
              disabled={busy || dirty || !eligible(photo)}
              onClick={() => void onApprove()}
            >
              Approve this photo
            </button>
          )}
        </div>
      </fieldset>
    </form>
  );
}
