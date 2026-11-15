import { useEffect, useRef, useState } from 'react';
import type { Schema } from '../api/types';
import { message } from '../api/client';
import * as workspaceApi from '../api/workspace';
import { getBatch } from '../features/review/api';
import { useAction } from '../hooks/useAction';
import { useUnsavedChanges } from '../hooks/useUnsavedChanges';
import Login from './Login';
import ImportBatch from './ImportBatch';
import SavedAlbums from './SavedAlbums';
import AppShell from './AppShell';
import type { Screen } from './AppShell';
import Administration from './Administration';
import BatchReview from '../features/review/BatchReview';
import type { ReviewInput, ReviewStatus } from '../features/review/BatchReview';

export default function Workspace() {
  const [session, setSession] = useState<Schema['SessionInfo'] | null>(null);
  const [checking, setChecking] = useState(true);
  const [screen, setScreen] = useState<Screen>('albums');
  const [albums, setAlbums] = useState<Schema['BatchSummary'][]>([]);
  const [disciplines, setDisciplines] = useState<Schema['DisciplineOption'][]>([]);
  const [review, setReview] = useState<ReviewInput | null>(null);
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus>({ name: '', running: false });
  const generation = useRef(0);
  const { error, notice, busy, action, setError, setNotice } = useAction();
  const changes = useUnsavedChanges();

  async function listAlbums() {
    setAlbums(await workspaceApi.listAlbums());
  }
  async function openBatch(id: string) {
    if (!changes.confirmLeave('Leave this photo without saving its changes?')) return;
    const view = await getBatch(id);
    changes.setDirty(false);
    setReview({ view, generation: ++generation.current });
    setReviewStatus({
      name: view.batch.album.name,
      running: view.jobs.some((job) => ['queued', 'running'].includes(job.state ?? '')),
    });
    setScreen('review');
    window.location.hash = `batch/${id}`;
  }
  async function initialize() {
    try {
      const session = await workspaceApi.currentSession();
      if (!session) return;
      setSession(session);
      await listAlbums();
      setDisciplines(await workspaceApi.listDisciplines());
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
            setSession(await workspaceApi.signIn(username, password));
            await listAlbums();
            setDisciplines(await workspaceApi.listDisciplines());
          });
        }}
        error={error}
        busy={busy}
      />
    );

  const messages = (
    <>
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
    </>
  );

  return (
    <AppShell
      session={session}
      screen={screen}
      albumCount={albums.length}
      albumName={reviewStatus.name}
      running={reviewStatus.running}
      onHome={() => {
        if (!changes.confirmLeave('Leave without saving caption changes?')) return;
        changes.setDirty(false);
        setScreen('albums');
      }}
      onAlbums={() =>
        void action(async () => {
          if (!changes.confirmLeave('Leave without saving caption changes?')) return;
          changes.setDirty(false);
          await listAlbums();
          setScreen('albums');
          window.location.hash = '';
        })
      }
      onNew={() => {
        if (!changes.confirmLeave('Leave without saving caption changes?')) return;
        changes.setDirty(false);
        setScreen('new');
        setError('');
      }}
      onAdmin={() => {
        if (!changes.confirmLeave('Leave without saving caption changes?')) return;
        changes.setDirty(false);
        setScreen('admin');
        setError('');
        setNotice('');
        window.location.hash = '';
      }}
      onSignOut={() =>
        void action(async () => {
          if (!changes.confirmLeave('Sign out without saving caption changes?')) return;
          if (
            reviewStatus.running &&
            !window.confirm(
              'Sign out and cancel analysis? Saved captions will be kept and temporary face data discarded.',
            )
          )
            return;
          await workspaceApi.signOut();
          changes.setDirty(false);
          setSession(null);
          setReview(null);
          setReviewStatus({ name: '', running: false });
        })
      }
    >
      {screen !== 'review' && (
        <div className="content">
          {messages}
          {screen === 'albums' && (
            <SavedAlbums
              albums={albums}
              onNew={() => setScreen('new')}
              onOpen={(id) => void action(() => openBatch(id))}
            />
          )}

          {screen === 'admin' && (
            <Administration
              onIntegrationChange={() =>
                void action(async () => {
                  setSession(await workspaceApi.currentSession());
                })
              }
              onDirty={(value) => {
                changes.setDirty(value);
              }}
            />
          )}
          {screen === 'new' && (
            <ImportBatch
              busy={busy}
              gallery={session.gallery_url ?? ''}
              onImport={(form) =>
                action(async () => {
                  const batch = await workspaceApi.importBatch(form);
                  await listAlbums();
                  await openBatch(batch.album.id);
                  setNotice(
                    'Inputs saved. Check the roster and photo count before starting analysis.',
                  );
                })
              }
            />
          )}
        </div>
      )}
      {review && (
        <BatchReview
          key={review.generation}
          initial={review}
          messages={messages}
          active={screen === 'review'}
          disciplines={disciplines}
          changes={changes}
          busy={busy}
          error={error}
          action={action}
          setError={setError}
          setNotice={setNotice}
          onStatus={setReviewStatus}
          onDelete={async () => {
            setReview(null);
            setReviewStatus({ name: '', running: false });
            await listAlbums();
            setScreen('albums');
            window.location.hash = '';
          }}
        />
      )}
    </AppShell>
  );
}
