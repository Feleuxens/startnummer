import { useEffect, useRef, useState } from 'react';
import type { SubmitEvent } from 'react';
import type { components } from '../api/schema';
import { api, message, unwrap } from '../api/client';
import FacePropagation from './FacePropagation';

type Schema = components['schemas'];
type Photo = Schema['Photo'];
type BatchView = Schema['BatchView'];
type FaceView = Schema['FaceView'];
type Selection = Schema['Selection'];
type Edit = Schema['Edit'];
type Preview = Schema['ChangePreview'];

const photoUrl = (id: string) => `${import.meta.env.PUBLIC_API_URL || ''}/api/photos/${id}`;
const approved = (photo: Photo) =>
  photo.approved_revision != null && photo.approved_revision === photo.revision;
const eligible = (photo: Photo) =>
  Boolean(
    photo.caption?.trim() &&
    photo.analysis &&
    (photo.analysis.record.status === 'auto' || photo.conflicts_resolved) &&
    (!photo.current_description ||
      photo.replace_existing ||
      photo.current_description === photo.caption),
  );
const selection = (photo: Photo): Selection => ({
  photo_id: photo.id,
  revision: photo.revision ?? 0,
});
const emptyFaces: FaceView = {
  available: false,
  session_id: null,
  photos: {},
  undo_count: 0,
  propagation_available: false,
};

export default function Workspace() {
  const [session, setSession] = useState<Schema['SessionInfo'] | null>(null);
  const [checking, setChecking] = useState(true);
  const [screen, setScreen] = useState<'albums' | 'new' | 'review'>('albums');
  const [albums, setAlbums] = useState<Schema['BatchSummary'][]>([]);
  const [view, setView] = useState<BatchView | null>(null);
  const [faces, setFaces] = useState<FaceView>(emptyFaces);
  const [disciplines, setDisciplines] = useState<Schema['DisciplineOption'][]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [subject, setSubject] = useState<number | null>(null);
  const [filter, setFilter] = useState('all');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<Preview[] | null>(null);
  const [propagation, setPropagation] = useState<Schema['PropagationPreview'] | null>(null);
  const [approvalPreview, setApprovalPreview] = useState<{
    batchId: string;
    albumName: string;
    photos: Photo[];
  } | null>(null);
  const [mobileDetail, setMobileDetail] = useState(false);
  const dirty = useRef(false);
  const batchId = view?.batch.album.id;

  async function listAlbums() {
    setAlbums(unwrap(await api.GET('/api/batches')));
  }
  async function loadBatch(id: string, first = false) {
    const data = unwrap(
      await api.GET('/api/batches/{batch_id}', { params: { path: { batch_id: id } } }),
    );
    setView(data);
    setFaces(
      unwrap(
        await api.GET('/api/batches/{batch_id}/faces', { params: { path: { batch_id: id } } }),
      ),
    );
    if (first) {
      setPropagation(null);
      setSelectedId(data.batch.photos[0]?.id ?? null);
      setSubject(null);
    }
    return data;
  }
  async function action(task: () => Promise<unknown>, success = '') {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await task();
      if (success && result !== false) setNotice(success);
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
    }
  }
  async function openBatch(id: string) {
    if (dirty.current && !window.confirm('Leave this photo without saving its changes?')) return;
    dirty.current = false;
    await loadBatch(id, true);
    setScreen('review');
    window.location.hash = `batch/${id}`;
  }
  async function initialize() {
    try {
      const result = await api.GET('/api/session');
      if (!result.data) return;
      setSession(result.data);
      await listAlbums();
      setDisciplines(unwrap(await api.GET('/api/disciplines')));
      const id = window.location.hash.match(/^#batch\/([a-f0-9-]+)$/)?.[1];
      if (id) await openBatch(id);
    } catch (failure) {
      setError(message(failure));
    } finally {
      setChecking(false);
    }
  }
  useEffect(() => {
    void initialize();
  }, []);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty.current) event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, []);
  const running =
    view?.jobs.some((job) => ['queued', 'running'].includes(job.state ?? '')) ?? false;
  useEffect(() => {
    if (!batchId || !running) return;
    let stopped = false;
    const timer = window.setInterval(() => {
      if (!stopped) void loadBatch(batchId).catch((failure) => setError(message(failure)));
    }, 1800);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [batchId, running]);
  useEffect(() => {
    if (!faces.available || !faces.expires_at) return;
    const timer = window.setTimeout(
      () => setFaces(emptyFaces),
      Math.max(0, faces.expires_at * 1000 - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [faces.expires_at, faces.available]);
  useEffect(() => {
    if (propagation && (!faces.available || propagation.face_session_id !== faces.session_id)) {
      setPropagation(null);
      setNotice('Face session ended. Saved names and captions are unchanged.');
    }
  }, [faces.available, faces.session_id, propagation]);

  async function approvePhotos(photos: Photo[], targetBatchId = batchId) {
    if (!targetBatchId || !photos.length) return;
    unwrap(
      await api.POST('/api/batches/{batch_id}/approve', {
        params: { path: { batch_id: targetBatchId } },
        body: { photos: photos.map(selection) },
      }),
    );
    await loadBatch(targetBatchId);
  }
  async function unapprovePhoto(photo: Photo) {
    if (!batchId) return;
    unwrap(
      await api.POST('/api/batches/{batch_id}/photos/{photo_id}/unapprove', {
        params: { path: { batch_id: batchId, photo_id: photo.id } },
        body: { revision: photo.revision },
      }),
    );
    await loadBatch(batchId);
  }
  function selectPhoto(photo: Photo) {
    if (busy) return;
    if (photo.id === selectedId) {
      setMobileDetail(true);
      return;
    }
    if (dirty.current && !window.confirm('Leave this photo without saving changes?')) return;
    dirty.current = false;
    setSelectedId(photo.id);
    setSubject(null);
    setMobileDetail(true);
    setError('');
    setNotice('');
  }
  async function confirmBulkApproval() {
    if (!approvalPreview) return;
    await approvePhotos(approvalPreview.photos, approvalPreview.batchId);
    const count = approvalPreview.photos.length;
    setApprovalPreview(null);
    setNotice(`${count} ${count === 1 ? 'caption' : 'captions'} approved in this album.`);
  }
  async function showPreview() {
    if (!batchId) return;
    if (dirty.current) throw new Error('Save the current photo before previewing gallery changes.');
    setPreview(
      unwrap(
        await api.GET('/api/batches/{batch_id}/apply-preview', {
          params: { path: { batch_id: batchId } },
        }),
      ),
    );
  }
  async function applyPreview() {
    if (!batchId || !preview) return;
    let result: Schema['Publication'][];
    try {
      result = unwrap(
        await api.POST('/api/batches/{batch_id}/apply', {
          params: { path: { batch_id: batchId } },
          body: { photos: preview.map((p) => ({ photo_id: p.photo_id, revision: p.revision })) },
        }),
      );
    } finally {
      // An interrupted batch may already have applied some descriptions. Load
      // its durable outcomes even when the overall HTTP request failed.
      await loadBatch(batchId);
    }
    setPreview(null);
    const conflicts = result.filter((p) =>
      ['conflict', 'failure'].includes(p.result?.state ?? ''),
    ).length;
    setNotice(
      `${result.length - conflicts} captions applied or unchanged; ${conflicts} conflicts or failures.`,
    );
  }

  async function findMatches(photo: Photo, subject: number) {
    if (!batchId || !faces.session_id) return;
    if (dirty.current) throw new Error('Save the name before finding matching faces.');
    setPropagation(
      unwrap(
        await api.POST('/api/batches/{batch_id}/face-propagation/preview', {
          params: { path: { batch_id: batchId } },
          body: { source: { ...selection(photo), subject }, face_session_id: faces.session_id },
        }),
      ),
    );
  }

  async function propagateNames(targets: Schema['FaceTarget'][], acknowledgeWarnings: boolean) {
    if (!batchId || !propagation) return;
    await action(
      async () => {
        unwrap(
          await api.POST('/api/batches/{batch_id}/face-propagation', {
            params: { path: { batch_id: batchId } },
            body: {
              source: propagation.source,
              face_session_id: propagation.face_session_id,
              targets,
              acknowledge_unsupported_bibs: acknowledgeWarnings,
              acknowledge_tentative_names: acknowledgeWarnings,
            },
          }),
        );
        setPropagation(null);
        await loadBatch(batchId);
      },
      `Name assigned to ${targets.length} selected ${targets.length === 1 ? 'photo' : 'photos'}. Review before approving.`,
    );
  }

  if (checking)
    return (
      <main className="login">
        <h1>Startnummer</h1>
        <p>Opening your workspace…</p>
      </main>
    );
  if (!session)
    return (
      <Login
        onLogin={async (username, password) => {
          await action(async () => {
            setSession(unwrap(await api.POST('/api/session', { body: { username, password } })));
            await listAlbums();
            setDisciplines(unwrap(await api.GET('/api/disciplines')));
          });
        }}
        error={error}
        busy={busy}
      />
    );

  const photos = view?.batch.photos ?? [];
  const latestPublication = new Map(
    view?.publications.map((operation) => [operation.photo_id, operation]),
  );
  const visible = photos.filter(
    (p) =>
      filter === 'all' ||
      (filter === 'unresolved' && p.analysis?.record.status !== 'auto' && !p.conflicts_resolved) ||
      (filter === 'approved' && approved(p)) ||
      (filter === 'unapproved' && !approved(p)) ||
      (filter === 'failed' && p.analysis?.record.status === 'failed') ||
      (filter === 'pending' && !p.analysis) ||
      (filter === 'publishing-issues' &&
        !latestPublication.get(p.id)?.restored &&
        ['pending', 'conflict', 'failure'].includes(
          latestPublication.get(p.id)?.result.state ?? '',
        )) ||
      (filter === 'published' &&
        !latestPublication.get(p.id)?.restored &&
        ['applied', 'unchanged'].includes(latestPublication.get(p.id)?.result.state ?? '')),
  );
  const selected = photos.find((p) => p.id === selectedId);
  const selectedPosition = photos.findIndex((p) => p.id === selectedId);
  const visibleIds = new Set(visible.map((p) => p.id));
  const previousPhoto = photos
    .slice(0, selectedPosition)
    .reverse()
    .find((p) => visibleIds.has(p.id));
  const nextPhoto = photos.slice(selectedPosition + 1).find((p) => visibleIds.has(p.id));
  const latestJob = view?.jobs[0];
  const approvedCount = photos.filter(approved).length;
  const eligibleUnapproved = photos.filter((p) => eligible(p) && !approved(p));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(event) => {
            event.preventDefault();
            if (dirty.current && !window.confirm('Leave without saving caption changes?')) return;
            dirty.current = false;
            setScreen('albums');
            setFaces(emptyFaces);
          }}
        >
          <span className="bib-mark" aria-hidden="true">
            #
          </span>
          <span>Startnummer</span>
        </a>
        <span className="scope">{session.username}</span>
        <nav aria-label="Workspace">
          <button
            className={screen === 'albums' ? 'active' : ''}
            onClick={() =>
              void action(async () => {
                if (dirty.current && !window.confirm('Leave without saving caption changes?'))
                  return;
                dirty.current = false;
                await listAlbums();
                setScreen('albums');
                window.location.hash = '';
              })
            }
          >
            Saved albums <span>{albums.length}</span>
          </button>
          <button
            className={screen === 'new' ? 'active' : ''}
            onClick={() => {
              if (dirty.current && !window.confirm('Leave without saving caption changes?')) return;
              dirty.current = false;
              setScreen('new');
              setError('');
            }}
          >
            New batch <span>+</span>
          </button>
        </nav>
        <p className="sidebar-note">
          Photos to captions.
          <br />
          Review before applying.
        </p>
        <button
          className="signout"
          onClick={() =>
            void action(async () => {
              if (dirty.current && !window.confirm('Sign out without saving caption changes?'))
                return;
              if (
                running &&
                !window.confirm(
                  'Sign out and cancel analysis? Saved captions will be kept and temporary face data discarded.',
                )
              )
                return;
              unwrap(await api.DELETE('/api/session'));
              dirty.current = false;
              setSession(null);
              setView(null);
              setFaces(emptyFaces);
            })
          }
        >
          {running ? 'Sign out and cancel analysis' : 'Sign out'}
        </button>
      </aside>
      <main className="canvas">
        <header className="topbar">
          <span>
            {screen === 'review'
              ? view?.batch.album.name
              : screen === 'new'
                ? 'New batch'
                : 'Your photo workspace'}
          </span>
          <span>{session.gallery_url ? 'Chevereto configured' : 'No gallery configured'}</span>
        </header>
        <div className={`content ${screen === 'review' && mobileDetail ? 'detail-open' : ''}`}>
          {error && (
            <div className="message error" role="alert">
              {error}
              <button onClick={() => setError('')}>Dismiss</button>
            </div>
          )}
          {notice && (
            <div className="message" role="status">
              {notice}
              <button onClick={() => setNotice('')}>Dismiss</button>
            </div>
          )}

          {screen === 'albums' && (
            <>
              <div className="title-row">
                <div>
                  <h1>Saved albums</h1>
                  <p>Pick up a review where you left it.</p>
                </div>
                <button className="primary" onClick={() => setScreen('new')}>
                  New batch
                </button>
              </div>
              {!albums.length ? (
                <div className="empty">
                  <h2>Your first album starts here</h2>
                  <p>
                    Import photos and a competition roster, then analyze and review the captions.
                  </p>
                  <button onClick={() => setScreen('new')}>Import a batch</button>
                </div>
              ) : (
                <div className="album-list">
                  {albums.map((album) => (
                    <button
                      className="album-row"
                      key={album.id}
                      onClick={() => void action(() => openBatch(album.id))}
                    >
                      <div>
                        <h2>{album.name}</h2>
                        <span>Saved {new Date(album.updated_at).toLocaleString()}</span>
                      </div>
                      <span>{album.photo_count} photos</span>
                      <span aria-hidden="true">→</span>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}

          {screen === 'new' && (
            <ImportBatch
              busy={busy}
              gallery={session.gallery_url ?? ''}
              onImport={(form) =>
                action(async () => {
                  const batch = unwrap(
                    await api.POST('/api/batches', {
                      body: form as never,
                      bodySerializer: (body) => body as unknown as FormData,
                    }),
                  );
                  await listAlbums();
                  await openBatch(batch.album.id);
                  setNotice(
                    'Inputs saved. Check the roster and photo count before starting analysis.',
                  );
                })
              }
            />
          )}

          {screen === 'review' && view && (
            <>
              <div className="title-row">
                <div>
                  <h1>{view.batch.album.name}</h1>
                  <p>
                    {photos.length} photos · {view.batch.roster.athletes?.length ?? 0} roster
                    entries · {approvedCount} approved
                  </p>
                </div>
                <div className="actions">
                  <button
                    disabled={busy || running || dirty.current}
                    onClick={() =>
                      void action(async () => {
                        if (dirty.current)
                          throw new Error('Save current changes before analyzing again.');
                        unwrap(
                          await api.POST('/api/batches/{batch_id}/analysis', {
                            params: { path: { batch_id: view.batch.album.id } },
                          }),
                        );
                        await loadBatch(view.batch.album.id);
                      })
                    }
                  >
                    {latestJob ? 'Analyze again' : 'Analyze batch'}
                  </button>
                  {running && (
                    <button
                      disabled={busy}
                      onClick={() =>
                        void action(async () => {
                          unwrap(
                            await api.POST('/api/batches/{batch_id}/analysis/cancel', {
                              params: { path: { batch_id: view.batch.album.id } },
                            }),
                          );
                          setFaces(emptyFaces);
                          await loadBatch(view.batch.album.id);
                        }, 'Analysis cancelled. Saved review work was kept.')
                      }
                    >
                      Cancel analysis
                    </button>
                  )}
                  <button
                    disabled={busy || running}
                    onClick={() =>
                      void action(async () => {
                        if (dirty.current)
                          throw new Error(
                            'Save the current caption before finishing the face session.',
                          );
                        unwrap(
                          await api.POST('/api/batches/{batch_id}/finish', {
                            params: { path: { batch_id: view.batch.album.id } },
                          }),
                        );
                        await loadBatch(view.batch.album.id);
                      }, 'Review saved. Extracted face data has been discarded.')
                    }
                  >
                    Save review and finish face session
                  </button>
                  <button
                    className="primary"
                    disabled={busy || running || !approvedCount}
                    onClick={() => void action(showPreview)}
                  >
                    Preview Apply
                  </button>
                </div>
              </div>

              {!latestJob && (
                <section className="import-preview">
                  <h2>Ready to analyze</h2>
                  <p>Meet: {view.batch.album.meet_name || 'Not supplied'}</p>
                  <p>
                    Roster sample:{' '}
                    {view.batch.roster.athletes
                      ?.slice(0, 3)
                      .map((a) => `${a.bib || '—'} · ${a.name}`)
                      .join(' / ')}
                  </p>
                </section>
              )}
              {latestJob && (
                <div className="job-strip" role="status">
                  <span className={`status ${latestJob.state}`}>{latestJob.state}</span>
                  <span>
                    {latestJob.phase} · {latestJob.completed} / {latestJob.total} photos
                  </span>
                  <progress
                    value={latestJob.completed}
                    max={latestJob.total || 1}
                    aria-label="Analysis progress"
                  />
                  {latestJob.error && <span className="error-text">{latestJob.error}</span>}
                </div>
              )}

              <div className="review-toolbar">
                <label>
                  Show{' '}
                  <select value={filter} onChange={(e) => setFilter(e.target.value)}>
                    <option value="all">All photos</option>
                    <option value="unresolved">Unresolved evidence</option>
                    <option value="unapproved">Not approved</option>
                    <option value="approved">Approved</option>
                    <option value="failed">Analysis failed</option>
                    <option value="pending">Not analyzed</option>
                    <option value="publishing-issues">Publishing needs attention</option>
                    <option value="published">Published</option>
                  </select>
                </label>
                <button
                  disabled={busy || running || !eligibleUnapproved.length}
                  onClick={() => {
                    setError('');
                    if (dirty.current) {
                      setError(
                        'Save the current photo’s changes before approving captions in bulk.',
                      );
                      return;
                    }
                    setApprovalPreview({
                      batchId: view.batch.album.id,
                      albumName: view.batch.album.name,
                      photos: eligibleUnapproved,
                    });
                  }}
                >
                  Approve all eligible ({eligibleUnapproved.length})…
                </button>
                {faces.available && faces.undo_id && faces.session_id && (
                  <button
                    disabled={busy || running}
                    onClick={() =>
                      void action(async () => {
                        if (dirty.current)
                          throw new Error('Save current edits before undoing a name assignment.');
                        if (
                          !window.confirm(
                            `Undo the last name assignment in ${faces.undo_count} photos? Approvals will be removed. Photos edited afterward cannot be undone.`,
                          )
                        )
                          return false;
                        unwrap(
                          await api.POST('/api/batches/{batch_id}/face-propagation/undo', {
                            params: { path: { batch_id: view.batch.album.id } },
                            body: { face_session_id: faces.session_id!, undo_id: faces.undo_id! },
                          }),
                        );
                        await loadBatch(view.batch.album.id);
                      }, 'Last name assignment undone. Review the affected captions before approving.')
                    }
                  >
                    Undo last name assignment ({faces.undo_count})
                  </button>
                )}
                <span className="muted">
                  Face selection{' '}
                  {faces.available
                    ? 'available for this session'
                    : 'unavailable · saved captions remain editable'}
                </span>
              </div>
              {faces.available && !faces.propagation_available && (
                <p className="worker-notice" role="status">
                  {faces.propagation_unavailable_reason ||
                    'Name propagation is unavailable for this worker session. Restart the updated API and worker, then analyze a fresh batch. Keep this batch to preserve your review edits.'}{' '}
                  Individual face naming remains available.
                </p>
              )}

              <div className={`review-grid ${mobileDetail ? 'show-detail' : ''}`}>
                <section className="contact-sheet" aria-label="Photo queue">
                  {visible.map((photo) => (
                    <button
                      key={photo.id}
                      disabled={busy}
                      className={`photo-tile ${photo.id === selectedId ? 'selected' : ''}`}
                      onClick={() => selectPhoto(photo)}
                    >
                      <img src={photoUrl(photo.id)} alt={photo.display_name} loading="lazy" />
                      <span>{photo.display_name}</span>
                      <small className={approved(photo) ? 'positive' : ''}>
                        {approved(photo)
                          ? 'Approved'
                          : photo.analysis?.record.status?.replaceAll('_', ' ') || 'Not analyzed'}
                      </small>
                    </button>
                  ))}
                  {!visible.length && <p className="empty">No photos match this filter.</p>}
                </section>
                {selected && (
                  <section className="photo-detail" aria-label="Selected photo">
                    <button className="mobile-back" onClick={() => setMobileDetail(false)}>
                      ← Back to photos
                    </button>
                    <div className="photo-heading">
                      <h2>{selected.display_name}</h2>
                    </div>
                    <div className="photo-viewer">
                      <div className="image-stage">
                        <div className="image-wrap">
                          <img src={photoUrl(selected.id)} alt={selected.display_name} />
                          {(faces.photos[selected.id] ?? []).map((face, index) => {
                            const [x1 = 0, y1 = 0, x2 = 0, y2 = 0] = face.box;
                            return (
                              <button
                                key={index}
                                className={`face-box ${face.subject === subject ? 'chosen' : ''}`}
                                aria-label={`Name detected face ${face.subject + 1}`}
                                style={{
                                  left: `${(100 * x1) / (selected.width || 1)}%`,
                                  top: `${(100 * y1) / (selected.height || 1)}%`,
                                  width: `${(100 * (x2 - x1)) / (selected.width || 1)}%`,
                                  height: `${(100 * (y2 - y1)) / (selected.height || 1)}%`,
                                }}
                                disabled={busy || running}
                                onClick={() => {
                                  if (dirty.current) {
                                    setError('Save current changes before selecting another face.');
                                    return;
                                  }
                                  setSubject(face.subject);
                                }}
                              >
                                <span>{face.subject + 1}</span>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                      <nav className="photo-navigation" aria-label="Photo navigation">
                        <button
                          type="button"
                          disabled={busy || !previousPhoto}
                          title={previousPhoto?.display_name}
                          onClick={() => {
                            if (previousPhoto) selectPhoto(previousPhoto);
                          }}
                        >
                          Previous photo
                        </button>
                        <span
                          aria-label={`Photo ${selectedPosition + 1} of ${photos.length} in album`}
                        >
                          {selectedPosition + 1} / {photos.length}
                        </span>
                        <button
                          type="button"
                          disabled={busy || !nextPhoto}
                          title={nextPhoto?.display_name}
                          onClick={() => {
                            if (nextPhoto) selectPhoto(nextPhoto);
                          }}
                        >
                          Next photo
                        </button>
                      </nav>
                    </div>
                    <Editor
                      key={`${selected.id}:${selected.revision}`}
                      photo={selected}
                      roster={view.batch.roster}
                      disciplines={disciplines}
                      subject={subject}
                      setSubject={setSubject}
                      faces={faces}
                      busy={busy || running}
                      onDirty={(value) => {
                        dirty.current = value;
                      }}
                      onSave={(patch) =>
                        action(async () => {
                          unwrap(
                            await api.PATCH('/api/batches/{batch_id}/photos/{photo_id}', {
                              params: {
                                path: { batch_id: view.batch.album.id, photo_id: selected.id },
                              },
                              body: patch,
                            }),
                          );
                          dirty.current = false;
                          await loadBatch(view.batch.album.id);
                        }, `Changes saved for ${selected.display_name}.`)
                      }
                      onApprove={() =>
                        action(
                          () => approvePhotos([selected]),
                          `Caption approved for ${selected.display_name}.`,
                        )
                      }
                      onUnapprove={() =>
                        action(
                          () => unapprovePhoto(selected),
                          `Approval removed for ${selected.display_name}.`,
                        )
                      }
                      onFindMatches={(index) => action(() => findMatches(selected, index))}
                      onAddPerson={(rosterIndex) =>
                        action(async () => {
                          if (dirty.current)
                            throw new Error('Save current edits before adding a person.');
                          const photo = unwrap(
                            await api.POST('/api/batches/{batch_id}/photos/{photo_id}/subjects', {
                              params: {
                                path: { batch_id: view.batch.album.id, photo_id: selected.id },
                              },
                              body: { revision: selected.revision, roster_index: rosterIndex },
                            }),
                          );
                          await loadBatch(view.batch.album.id);
                          setSubject((photo.analysis?.record.subjects.length ?? 1) - 1);
                        }, 'Person added. Review the generated caption before approving.')
                      }
                      onRemovePerson={(index) =>
                        action(async () => {
                          if (dirty.current)
                            throw new Error('Save current edits before removing a person.');
                          if (
                            !window.confirm(
                              'Remove this added person from the photo and regenerate the caption suggestion?',
                            )
                          )
                            return false;
                          unwrap(
                            await api.DELETE(
                              '/api/batches/{batch_id}/photos/{photo_id}/subjects/{subject_index}',
                              {
                                params: {
                                  path: {
                                    batch_id: view.batch.album.id,
                                    photo_id: selected.id,
                                    subject_index: index,
                                  },
                                },
                                body: { revision: selected.revision },
                              },
                            ),
                          );
                          setSubject(null);
                          await loadBatch(view.batch.album.id);
                        }, 'Added person removed. Review the caption before approving.')
                      }
                    />
                  </section>
                )}
              </div>
              <section className="publishing-history">
                <h2>Publishing history</h2>
                {!view.publications.length ? (
                  <p className="muted">No descriptions have been applied from this batch.</p>
                ) : (
                  view.publications.map((operation) => (
                    <div className="history-row" key={operation.id}>
                      <span>{photos.find((p) => p.id === operation.photo_id)?.display_name}</span>
                      <span className={operation.result?.state === 'conflict' ? 'error-text' : ''}>
                        {operation.restored ? 'restored' : operation.result?.state}
                      </span>
                      {operation.result?.error && <span>{operation.result.error}</span>}
                      {operation.result?.state === 'conflict' && (
                        <span>Live description: {operation.result.live_value ?? '(empty)'}</span>
                      )}
                      {!operation.restored &&
                        ['pending', 'failure', 'conflict'].includes(operation.result.state) && (
                          <>
                            <button
                              disabled={busy || running}
                              onClick={() =>
                                void action(async () => {
                                  if (dirty.current)
                                    throw new Error(
                                      'Save current edits before checking the gallery.',
                                    );
                                  const result = unwrap(
                                    await api.POST(
                                      '/api/batches/{batch_id}/publications/{operation_id}/reconcile',
                                      {
                                        params: {
                                          path: {
                                            batch_id: view.batch.album.id,
                                            operation_id: operation.id,
                                          },
                                        },
                                      },
                                    ),
                                  );
                                  await loadBatch(view.batch.album.id);
                                  setNotice(
                                    result.result.state === 'unchanged'
                                      ? 'Gallery change confirmed. No description was written.'
                                      : result.result.error ||
                                          'Gallery differs from this operation. Load its live description to review.',
                                  );
                                })
                              }
                            >
                              Check gallery outcome
                            </button>
                            <button
                              disabled={busy || running}
                              onClick={() =>
                                void action(async () => {
                                  if (dirty.current)
                                    throw new Error(
                                      'Save current edits before loading the gallery description.',
                                    );
                                  const photo = photos.find(
                                    (photo) => photo.id === operation.photo_id,
                                  );
                                  if (!photo) return;
                                  unwrap(
                                    await api.POST(
                                      '/api/batches/{batch_id}/photos/{photo_id}/refresh-description',
                                      {
                                        params: {
                                          path: {
                                            batch_id: view.batch.album.id,
                                            photo_id: photo.id,
                                          },
                                        },
                                        body: { revision: photo.revision },
                                      },
                                    ),
                                  );
                                  await loadBatch(view.batch.album.id);
                                  selectPhoto(photo);
                                }, 'Live description loaded. Review and approve the replacement again.')
                              }
                            >
                              Load live description for review
                            </button>
                          </>
                        )}
                      {!operation.restored &&
                        ['applied', 'unchanged'].includes(operation.result?.state ?? '') && (
                          <button
                            disabled={busy}
                            onClick={() =>
                              void action(async () => {
                                if (dirty.current)
                                  throw new Error(
                                    'Save current edits before restoring a description.',
                                  );
                                if (
                                  !window.confirm(
                                    'Restore the previous gallery description? This succeeds only if it has not changed since Apply.',
                                  )
                                )
                                  return false;
                                const result = unwrap(
                                  await api.POST(
                                    '/api/batches/{batch_id}/publications/{operation_id}/restore',
                                    {
                                      params: {
                                        path: {
                                          batch_id: view.batch.album.id,
                                          operation_id: operation.id,
                                        },
                                      },
                                    },
                                  ),
                                );
                                if (['conflict', 'failure'].includes(result.state))
                                  throw new Error(
                                    result.error ||
                                      'Gallery description changed; restore was not applied.',
                                  );
                                await loadBatch(view.batch.album.id);
                              }, 'Previous description restored.')
                            }
                          >
                            Restore previous description
                          </button>
                        )}
                    </div>
                  ))
                )}
              </section>
              <button
                className="danger-text"
                disabled={busy || running}
                onClick={() =>
                  void action(async () => {
                    if (
                      !window.confirm(
                        `Delete this saved batch and its ${photos.length} local photos? Chevereto images will remain.`,
                      )
                    )
                      return;
                    unwrap(
                      await api.DELETE('/api/batches/{batch_id}', {
                        params: { path: { batch_id: view.batch.album.id } },
                      }),
                    );
                    dirty.current = false;
                    setView(null);
                    setFaces(emptyFaces);
                    await listAlbums();
                    setScreen('albums');
                    window.location.hash = '';
                  })
                }
              >
                Delete saved batch…
              </button>
            </>
          )}
        </div>
      </main>
      {propagation && (
        <FacePropagation
          preview={propagation}
          photos={photos}
          busy={busy}
          error={error}
          onClose={() => setPropagation(null)}
          onApply={propagateNames}
          onReview={async (target) => {
            if (!batchId) return;
            await action(async () => {
              const data = await loadBatch(batchId);
              const photo = data.batch.photos.find((photo) => photo.id === target.photo_id);
              if (!photo) throw new Error('This photo is no longer available.');
              setPropagation(null);
              setSelectedId(photo.id);
              setSubject(photo.revision === target.revision ? target.subject : null);
              setMobileDetail(true);
            });
          }}
        />
      )}
      {approvalPreview && (
        <dialog
          className="apply-dialog"
          aria-labelledby="approval-title"
          ref={(node) => {
            if (node && !node.open) node.showModal();
          }}
          onCancel={(event) => {
            if (busy) event.preventDefault();
            else setApprovalPreview(null);
          }}
        >
          <h2 id="approval-title">Approve all eligible captions?</h2>
          <p>
            {approvalPreview.photos.length}{' '}
            {approvalPreview.photos.length === 1 ? 'photo' : 'photos'} in{' '}
            {approvalPreview.albumName}. This covers the whole album, including photos hidden by the
            current filter.
          </p>
          <p>
            Blank captions, unresolved photos, and already approved captions are excluded. Applying
            descriptions to Chevereto is a separate action.
          </p>
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
          <ul className="approval-list">
            {approvalPreview.photos.map((photo) => (
              <li key={photo.id}>
                <h3>{photo.display_name}</h3>
                <p>{photo.caption}</p>
              </li>
            ))}
          </ul>
          <div className="actions">
            <button autoFocus disabled={busy} onClick={() => setApprovalPreview(null)}>
              Cancel
            </button>
            <button
              className="primary"
              disabled={busy}
              onClick={() => void action(confirmBulkApproval)}
            >
              {busy
                ? 'Approving…'
                : `Approve ${approvalPreview.photos.length} ${approvalPreview.photos.length === 1 ? 'caption' : 'captions'}`}
            </button>
          </div>
        </dialog>
      )}
      {preview && (
        <dialog
          className="apply-dialog"
          aria-labelledby="apply-title"
          ref={(node) => {
            if (node && !node.open) node.showModal();
          }}
          onCancel={(event) => {
            if (busy) event.preventDefault();
            else setPreview(null);
          }}
        >
          <h2 id="apply-title">Apply approved descriptions</h2>
          <p>{preview.length} mapped photos · description changes only</p>
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
          {!preview.length && <p>No approved captions have a gallery destination.</p>}
          {preview.map((change) => (
            <div className="change-preview" key={change.photo_id}>
              <h3>{change.display_name}</h3>
              <div>
                <span>Current</span>
                <p>{change.change.expected ?? '(empty)'}</p>
              </div>
              <div>
                <span>Approved</span>
                <p>{change.change.replacement}</p>
              </div>
            </div>
          ))}
          <div className="actions">
            <button disabled={busy} onClick={() => setPreview(null)}>
              Back to review
            </button>
            <button
              className="primary"
              disabled={busy || !preview.length}
              onClick={() => void action(applyPreview)}
            >
              {busy ? 'Applying…' : 'Apply to Chevereto'}
            </button>
          </div>
        </dialog>
      )}
    </div>
  );
}

function Login({
  onLogin,
  error,
  busy,
}: {
  onLogin: (username: string, password: string) => Promise<void>;
  error: string;
  busy: boolean;
}) {
  return (
    <main className="login">
      <div className="brand">
        <span className="bib-mark">#</span>Startnummer
      </div>
      <h1>Your photos. The right names.</h1>
      <p>Sign in to import, analyze, and review your sports photo captions.</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          void onLogin(String(data.get('username')), String(data.get('password')));
        }}
      >
        <label>
          Username
          <input name="username" autoComplete="username" defaultValue="photographer" required />
        </label>
        <label>
          Password
          <input name="password" type="password" autoComplete="current-password" required />
        </label>
        {error && (
          <p role="alert" className="error-text">
            {error}
          </p>
        )}
        <button className="primary" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  );
}

function ImportBatch({
  onImport,
  busy,
  gallery,
}: {
  onImport: (data: FormData) => Promise<void>;
  busy: boolean;
  gallery: string;
}) {
  const [photoSource, setPhotoSource] = useState('gallery');
  const [rosterSource, setRosterSource] = useState('file');
  const [uploadNames, setUploadNames] = useState<string[]>([]);
  const importId = useRef(crypto.randomUUID());
  return (
    <>
      <div className="title-row">
        <div>
          <h1>New batch</h1>
          <p>Choose photos and a competition roster independently.</p>
        </div>
      </div>
      <form
        className="import-form"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          form.set('import_id', importId.current);
          void onImport(form);
        }}
      >
        <section>
          <h2>Photos</h2>
          <div className="source-choices">
            <label>
              <input
                type="radio"
                checked={photoSource === 'gallery'}
                onChange={() => setPhotoSource('gallery')}
              />{' '}
              Chevereto album
            </label>
            <label>
              <input
                type="radio"
                checked={photoSource === 'files'}
                onChange={() => setPhotoSource('files')}
              />{' '}
              Upload images
            </label>
          </div>
          {photoSource === 'gallery' ? (
            <label>
              Album URL
              <input
                name="gallery_url"
                type="url"
                placeholder={
                  gallery ? `${gallery}/album/…` : 'Configure a gallery to import an album'
                }
                required
              />
            </label>
          ) : (
            <label>
              Image files
              <input
                name="photos"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                multiple
                required
                onChange={(event) => {
                  const names = Array.from(event.target.files ?? []).map((file) => file.name);
                  setUploadNames(names);
                }}
              />
              <small>
                JPEG, PNG, or WebP. Select originals rather than generated face/annotation previews.
              </small>
              {uploadNames.length > 0 && <span>{uploadNames.length} photos selected</span>}
            </label>
          )}
        </section>
        <section>
          <h2>Competition roster</h2>
          <div className="source-choices">
            <label>
              <input
                type="radio"
                checked={rosterSource === 'file'}
                onChange={() => setRosterSource('file')}
              />{' '}
              Upload HTML
            </label>
            <label>
              <input
                type="radio"
                checked={rosterSource === 'url'}
                onChange={() => setRosterSource('url')}
              />{' '}
              Supported URL
            </label>
          </div>
          {rosterSource === 'file' ? (
            <label>
              Competitoroverview HTML
              <input name="roster_file" type="file" accept=".html,.htm,text/html" required />
            </label>
          ) : (
            <label>
              Roster URL
              <input
                name="roster_url"
                type="url"
                placeholder="https://ergebnisse.leichtathletik.de/…"
                required
              />
            </label>
          )}
        </section>
        <section className="import-details">
          <h2>Batch details</h2>
          <label>
            Album name
            <input name="name" placeholder="Saturday track meet" />
          </label>
          <label>
            Meet name
            <input
              name="meet_name"
              aria-label="Meet name"
              placeholder="Competition name used in captions"
            />
            <small>Separate from the discipline. Leave blank if unavailable.</small>
          </label>
        </section>
        <div className="import-footer">
          <p>
            Import saves the inputs. You can check the photo count and roster before starting
            analysis.
          </p>
          <button className="primary" disabled={busy}>
            {busy ? 'Importing photos and roster…' : 'Import and preview'}
          </button>
        </div>
      </form>
    </>
  );
}

function Editor({
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
  const peopleToAdd = (roster.athletes ?? [])
    .map((person, index) => ({ person, index }))
    .filter(({ person }) =>
      [person.name, person.bib, person.club]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase()
        .includes(rosterQuery.trim().toLocaleLowerCase()),
    );
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
                      {[person.bib, person.name, person.club].filter(Boolean).join(' · ')}
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
                  {roster.athletes
                    ?.filter((a) => a.bib)
                    .map((athlete, index) => (
                      <option key={`${athlete.bib}-${index}`} value={athlete.bib ?? ''}>
                        {athlete.bib} · {athlete.name}
                      </option>
                    ))}
                </select>
              </label>
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
            <select
              value={'discipline' in patch ? (patch.discipline ?? '') : discipline}
              onChange={(event) =>
                update({
                  discipline:
                    disciplines.find((d) => d.value === event.target.value)?.value ?? null,
                })
              }
            >
              <option value="">Undetermined</option>
              {disciplines.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.value === 'no_event'
                    ? 'No event (explicit decision)'
                    : d.value === 'other'
                      ? 'Other / unspecified'
                      : `${d.de} / ${d.en}`}
                </option>
              ))}
            </select>
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
