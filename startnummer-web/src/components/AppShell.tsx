import type { ReactNode } from 'react';
import type { Schema } from '../api/types';

export type Screen = 'albums' | 'new' | 'review' | 'admin' | 'account';

export default function AppShell({
  session,
  screen,
  albumCount,
  albumName,
  running,
  onHome,
  onAlbums,
  onNew,
  onAdmin,
  onAccount,
  onSignOut,
  children,
}: {
  session: Schema['SessionInfo'];
  screen: Screen;
  albumCount: number;
  albumName?: string;
  running: boolean;
  onHome: () => void;
  onAlbums: () => void;
  onNew: () => void;
  onAdmin: () => void;
  onAccount: () => void;
  onSignOut: () => void;
  children: ReactNode;
}) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(event) => {
            event.preventDefault();
            onHome();
          }}
        >
          <span className="bib-mark" aria-hidden="true">
            #
          </span>
          <span>Startnummer</span>
        </a>
        <span className="scope">{session.username}</span>
        <nav aria-label="Workspace">
          <button className={screen === 'albums' ? 'active' : ''} onClick={onAlbums}>
            Saved albums <span>{albumCount}</span>
          </button>
          <button className={screen === 'new' ? 'active' : ''} onClick={onNew}>
            New batch <span>+</span>
          </button>
        </nav>
        <div className="sidebar-footer">
          <nav aria-label="Account">
            <button className={screen === 'account' ? 'active' : ''} onClick={onAccount}>
              Account
            </button>
            {session.is_admin && (
              <button className={screen === 'admin' ? 'active' : ''} onClick={onAdmin}>
                Administration
              </button>
            )}
            <button onClick={onSignOut}>
              {running ? 'Sign out and cancel analysis' : 'Sign out'}
            </button>
          </nav>
        </div>
      </aside>
      <main className="canvas">
        <header className="topbar">
          <span>
            {screen === 'review'
              ? albumName
              : screen === 'new'
                ? 'New batch'
                : screen === 'account'
                  ? 'Account'
                  : screen === 'admin'
                    ? 'Administration'
                    : 'Your photo workspace'}
          </span>
        </header>
        {children}
      </main>
    </div>
  );
}
