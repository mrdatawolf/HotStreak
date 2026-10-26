import { useState, type FormEvent } from 'react'
import { api, errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext'

export default function AccountPage() {
  const { me } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirmNext, setConfirmNext] = useState('')
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (next !== confirmNext) {
      setMessage({ kind: 'error', text: "New passwords don't match" })
      return
    }
    const { error } = await api.POST('/api/auth/password', { body: { current_password: current, new_password: next } })
    if (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
      return
    }
    setCurrent('')
    setNext('')
    setConfirmNext('')
    setMessage({ kind: 'ok', text: 'Password changed. Other devices have been signed out.' })
  }

  return (
    <section>
      <h1>Account</h1>
      <p className="lede">{me?.name} · {me?.email} · {me?.is_admin ? 'Admin' : 'User'}</p>
      <form className="panel settings-block stack" onSubmit={submit}>
        <h2>Change password</h2>
        <label>Current password
          <input type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
        </label>
        <label>New password (10+ characters)
          <input type="password" autoComplete="new-password" minLength={10} required value={next} onChange={(e) => setNext(e.target.value)} />
        </label>
        <label>Confirm new password
          <input type="password" autoComplete="new-password" minLength={10} required value={confirmNext} onChange={(e) => setConfirmNext(e.target.value)} />
        </label>
        {message && <p className={message.kind === 'ok' ? 'form-ok' : 'form-error'} role="status">{message.text}</p>}
        <button className="primary">Change password</button>
      </form>
    </section>
  )
}
