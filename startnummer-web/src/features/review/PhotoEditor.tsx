import { useState } from 'react';
import type { SubmitEvent } from 'react';
import type { Schema, Photo, Edit, FaceView } from '../../api/types';
import DisciplineSelect from '../../components/DisciplineSelect';
import SubjectEditor from './SubjectEditor';
import type { SubjectDraft } from './SubjectEditor';
import { matchesRosterQuery, rosterPersonLabel, approved, canApprove } from './model';

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
  onRefreshSuggestion,
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
  onRefreshSuggestion: () => Promise<void>;
  onFindMatches: (subject: number) => Promise<void>;
  onAddPerson: (rosterIndex: number) => Promise<void>;
  onRemovePerson: (subject: number) => Promise<void>;
}) {
  const [caption, setCaption] = useState(photo.caption ?? '');
  const [replace, setReplace] = useState(photo.replace_existing ?? false);
  const [patch, setPatch] = useState<Partial<Edit>>({});
  const [dirty, setDirty] = useState(false);
  const [rosterQuery, setRosterQuery] = useState('');
  const [rosterIndex, setRosterIndex] = useState('');
  const [subjectEdits, setSubjectEdits] = useState<Record<number, SubjectDraft>>({});
  const [useGenerated, setUseGenerated] = useState(false);
  const peopleToAdd = (roster.athletes ?? [])
    .map((person, index) => ({ person, index }))
    .filter(({ person }) => matchesRosterQuery(person, rosterQuery));
  const record = photo.analysis?.record;
  const hasRoster = !!roster.athletes?.length;
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

  const updateSubject = (index: number, draft: SubjectDraft) => {
    setSubjectEdits((previous) => ({ ...previous, [index]: draft }));
    mark();
  };

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const body: Edit = {
      revision: photo.revision ?? 0,
      replace_existing: replace,
      conflicts_resolved: photo.conflicts_resolved,
      use_generated_caption: useGenerated,
      ...patch,
      subjects: Object.entries(subjectEdits).map(([key, draft]) => {
        const index = Number(key);
        const identityChanged = ['athlete_name', 'roster_bib', 'roster_index', 'bib', 'club'].some(
          (key) => key in draft,
        );
        return {
          ...draft,
          subject: index,
          ...(identityChanged &&
          faces.available &&
          faces.session_id &&
          faces.photos[photo.id]?.some((face) => face.subject === index)
            ? { face_session_id: faces.session_id }
            : {}),
        };
      }),
    };
    if (!useGenerated && caption !== (photo.caption ?? '')) body.caption = caption;
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
                setUseGenerated(false);
                mark();
              }}
            />
          </label>
        </div>
        {record && (
          <button
            type="button"
            className="refresh-caption"
            disabled={busy || dirty}
            onClick={() => void onRefreshSuggestion()}
          >
            Refresh caption suggestion
          </button>
        )}
        {record && ((photo.proposal ?? '') !== caption || photo.caption_edited) && (
          <details open={photo.caption_edited}>
            <summary>Analysis suggestion</summary>
            <p>{photo.proposal || 'No included person has a matched name.'}</p>
            <button
              type="button"
              onClick={() => {
                setCaption(photo.proposal ?? '');
                setUseGenerated(true);
                mark();
              }}
            >
              Use generated caption
            </button>
          </details>
        )}
        {photo.caption_edited &&
          !useGenerated &&
          subjects.some(
            (item, index) =>
              subjectEdits[index]?.excluded_from_caption ?? item.excluded_from_caption,
          ) && (
            <p className="muted">
              Your manually edited caption is kept. Save the changes to see the updated generated
              suggestion.
            </p>
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
              {hasRoster
                ? record
                  ? 'No subjects detected. Add someone from the roster to generate a caption.'
                  : 'Add someone from the roster, or analyze the batch to detect subjects.'
                : record
                  ? 'No subjects detected. You can enter a caption manually.'
                  : 'Analyze the batch to detect people, then name them during review.'}
            </p>
          )}
          {hasRoster && (
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
          )}
          {subjects.length > 1 && (
            <p className="muted">Edit any person, then save all corrections together.</p>
          )}
          {subjects.map((item, index) => {
            const draft = subjectEdits[index];
            const excluded = draft?.excluded_from_caption ?? item.excluded_from_caption;
            const chosen =
              draft?.roster_index != null
                ? roster.athletes?.[draft.roster_index]
                : draft?.roster_bib
                  ? roster.athletes?.find((person) => person.bib === draft.roster_bib)
                  : undefined;
            const name =
              draft?.athlete_name || chosen?.name || item.athlete?.value.name || 'Name not matched';
            return (
              <div className="subject-choice" key={index}>
                <button
                  type="button"
                  className={`subject-row ${subject === index ? 'selected' : ''}`}
                  onClick={() => setSubject(subject === index ? null : index)}
                >
                  <span>{index + 1}</span>
                  <div>
                    <strong>{name}</strong>
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
                    {excluded && <small>Excluded from caption</small>}
                    {draft && <small>Unsaved changes</small>}
                  </div>
                </button>
                <button
                  type="button"
                  className="subject-exclusion"
                  aria-label={`${excluded ? 'Include' : 'Exclude'} person ${index + 1} ${excluded ? 'in' : 'from'} caption`}
                  onClick={() =>
                    updateSubject(index, { ...draft, excluded_from_caption: !excluded })
                  }
                >
                  {excluded ? 'Include' : 'Exclude'}
                </button>
              </div>
            );
          })}
          {currentSubject && subject != null && (
            <SubjectEditor
              key={subject}
              subject={currentSubject}
              roster={roster}
              draft={subjectEdits[subject] ?? {}}
              onChange={(draft) => updateSubject(subject, draft)}
              canFindMatches={
                !busy &&
                !dirty &&
                faces.available &&
                faces.propagation_available &&
                currentSubject.athlete?.source === 'manual' &&
                !!faces.photos[photo.id]?.some((face) => face.subject === subject)
              }
              onFindMatches={() => void onFindMatches(subject)}
              canRemove={!busy && !dirty}
              onRemove={() => void onRemovePerson(subject)}
            />
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
              disabled={busy || dirty || !canApprove(photo)}
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
