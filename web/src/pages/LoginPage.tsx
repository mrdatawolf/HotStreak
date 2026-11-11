import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router'
import { useAuth } from '../auth/AuthContext'
import FontPicker from '../components/FontPicker'
import ThemeToggle from '../components/ThemeToggle'

/** Only allow in-app redirects after sign-in. */
function safeNext(next: string | null) {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/board'
}

export default function LoginPage() {
  const { me, login } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (me && me.role !== 'board') return <Navigate to={next} replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    const err = await login(username, password)
    setBusy(false)
    if (err) setError(err)
    else navigate(next, { replace: true })
  }

  return (
    <main className="login">
      <form className="panel login-card" onSubmit={submit}>
        <h1>HotStreak</h1>
        <label>
          Email
          <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label>
          Password
          <input type="password" autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <div className="login-theme"><FontPicker /><ThemeToggle /></div>
    </main>
  )
}
