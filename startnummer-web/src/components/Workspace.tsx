import { useEffect, useRef, useState } from 'react';
import type { Schema } from '../api/types';
import { message } from '../api/client';
import * as workspaceApi from '../api/workspace';
import { getBatch } from '../features/review/api';
import { useAction } from '../hooks/useAction';
import { useUnsavedChanges } from '../hooks/useUnsavedChanges';
import Login from './Login';
import AccountSettings from '../features/accounts/AccountSettings';
import ImportBatch from './ImportBatch';
import SavedAlbums from './SavedAlbums';
import AppShell from './AppShell';
import type { Screen } from './AppShell';
import Administration from './Administration';
import BatchReview from '../features/review/BatchReview';
import type { ReviewInput, ReviewStatus } from '../features/review/BatchReview';

export default function Workspace() {
  const [session, setSession] = useState<Schema['SessionInfo'] | null>(null);
  const [authStatus, setAuthStatus] = useState<Schema['AuthStatus'] | null>(null);
  const authGeneration = useRef(0);
  const authenticated = useRef(false);
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
    const generation = authGeneration.current;
    const result = await workspaceApi.listAlbums();
    if (generation === authGeneration.current) setAlbums(result);
  }
  function clearSession() {
    authenticated.current = false;
    ++authGeneration.current;
    changes.setDirty(false);
    setSession(null);
    setReview(null);
    setAlbums([]);
    setDisciplines([]);
    setReviewStatus({ name: '', running: false });
    setScreen('albums');
    window.location.hash = '';
  }
  async function loadDisciplines() {
    const generation = authGeneration.current;
    const result = await workspaceApi.listDisciplines();
    if (generation === authGeneration.current) setDisciplines(result);
  }
  async function openBatch(id: string) {
    if (!changes.confirmLeave('Leave this photo without saving its changes?')) return;
    const auth = authGeneration.current;
    const view = await getBatch(id);
    if (auth !== authGeneration.current) return;
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
      setAuthStatus(await workspaceApi.authStatus());
      const session = await workspaceApi.currentSession();
      if (!session) return;
      authenticated.current = true;
      setSession(session);
      await listAlbums();
      await loadDisciplines();
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
    const expired = () => {
      if (!authenticated.current) return;
      clearSession();
      setError('Your session ended. Sign in again.');
    };
    window.addEventListener('startnummer:session-expired', expired);
    return () => window.removeEventListener('startnummer:session-expired', expired);
  }, []);
  useEffect(() => {
    if (!session) return;
    const check = () => {
      void workspaceApi.currentSession().catch(() => {});
    };
    const timer = window.setInterval(check, 30000);
    window.addEventListener('focus', check);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', check);
    };
  }, [Boolean(session)]);
  if (checking)
    return (
      <main className="login">
        <h1>Startnummer</h1>
        <p>Opening your workspace…</p>
      </main>
    );
  if (!session)
    return authStatus ? (
      <Login
        status={authStatus}
        onSubmit={async (mode, credentials) => {
          await action(async () => {
            const result =
              mode === 'login'
                ? await workspaceApi.signIn(credentials.username, credentials.password)
                : mode === 'setup'
                  ? await workspaceApi.setup({ ...credentials, code: credentials.code ?? '' })
                  : await workspaceApi.register(credentials);
            ++authGeneration.current;
            authenticated.current = true;
            setSession(result);
            window.location.hash = '';
            setScreen('albums');
            await listAlbums();
            await loadDisciplines();
            setAuthStatus(await workspaceApi.authStatus());
          });
        }}
        error={error}
        busy={busy}
      />
    ) : (
      <main className="login">
        <h1>Startnummer</h1>
        <p role="alert">{error || 'Could not load account settings.'}</p>
        <button onClick={() => void initialize()}>Try again</button>
      </main>
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
      onAccount={() => {
        if (!changes.confirmLeave('Leave without saving changes?')) return;
        changes.setDirty(false);
        setScreen('account');
        setError('');
        setNotice('');
        window.location.hash = '';
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
          clearSession();
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

          {screen === 'account' && (
            <AccountSettings
              onDirty={changes.setDirty}
              onSignedOut={clearSession}
              onSessionsCleared={() => {
                ++authGeneration.current;
                setReview(null);
                setReviewStatus({ name: '', running: false });
              }}
            />
          )}
          {screen === 'admin' && session.is_admin && (
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
              canUseGallery={Boolean(session.is_admin)}
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
          canPublish={Boolean(session.is_admin)}
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
