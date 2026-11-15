export default function Login({
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
