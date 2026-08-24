import { useState, type FormEvent } from "react";

import { useLogin } from "../api/hooks";
import { IcArrow } from "../components/Icons";

export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("demo@kira.app");
  const [password, setPassword] = useState("demo-money-butler");
  const login = useLogin();

  function submit(event: FormEvent) {
    event.preventDefault();
    login.mutate({ email, password }, { onSuccess: onSignedIn });
  }

  return (
    <div className="pad" style={{ paddingTop: 80 }}>
      <p className="eyebrow" style={{ margin: 0 }}>Welcome back</p>
      <h1 style={{ marginTop: 6 }}>Sign in to Kira</h1>
      <form onSubmit={submit} style={{ marginTop: 24, display: "grid", gap: 12 }}>
        <input
          className="field"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          aria-label="Email"
          autoComplete="username"
        />
        <input
          className="field"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          aria-label="Password"
          autoComplete="current-password"
        />
        <button className="btn btn-primary" type="submit" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"} <IcArrow size={15} />
        </button>
        {login.isError && (
          <p style={{ margin: 0, fontSize: 13, color: "var(--clay)" }}>
            That email and password don't match.
          </p>
        )}
      </form>
    </div>
  );
}
