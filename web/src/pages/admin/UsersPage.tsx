import { useCallback, useState, type FormEvent } from 'react'
import { api, errorMessage, type Rep, type User } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import CrudTable, { type Field, type Values } from '../../components/CrudTable'
import { useLoad } from '../../lib/useLoad'

const ROLES = [
  { value: 'user', label: 'User' },
  { value: 'admin', label: 'Admin' },
] as const

const isLocked = (u: User) => !!u.locked_until && new Date(u.locked_until + 'Z') > new Date()

/** The Rep cell: whose sales a user's reports show. Users must have one; admins see everything anyway. */
function RepCell({ user }: { user: User }) {
  if (user.rep_name) return <>{user.rep_name}</>
  if (user.role === 'user' && user.active) return <span className="badge warn">Needs rep</span>
  return <span className="muted">{user.role === 'admin' ? 'All (admin)' : '—'}</span>
}

function fields(reps: Rep[]): Field[] {
  return [
    { key: 'name', label: 'Name', required: true },
    { key: 'email', label: 'Email', type: 'email', required: true },
    { key: 'role', label: 'Role', type: 'select', options: ROLES },
    {
      key: 'rep_id', label: 'Rep (required for users)', type: 'select',
      // Inactive reps stay listed so a user already linked to one still shows it; the API only refuses picking one anew.
      options: [{ value: '', label: '— Pick a rep —' },
        ...reps.map((r) => ({ value: String(r.id), label: r.active ? r.name : `${r.name} (inactive)` }))],
      render: (u: User) => <RepCell user={u} />,
    },
    { key: 'active', label: 'Active', type: 'checkbox' },
    { key: 'password', label: 'Password (10+ characters)', type: 'password', required: true, createOnly: true },
    {
      key: 'locked_until', label: 'Status', readOnly: true,
      render: (u: User) => (isLocked(u)
        ? <span className="badge warn">Locked until {new Date(u.locked_until + 'Z').toLocaleTimeString()}</span>
        : <span className="muted">OK</span>),
    },
  ]
}

const repIdOf = (v: Values) => (v.rep_id ? Number(v.rep_id) : null)

function ResetPassword({ user, onError }: { user: User; onError: (e: string | null) => void }) {
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    const { error } = await api.POST('/api/users/{user_id}/password', {
      params: { path: { user_id: user.id } }, body: { password },
    })
    onError(error ? errorMessage(error) : null)
    if (!error) {
      setOpen(false)
      setPassword('')
    }
  }

  if (!open) return <button onClick={() => setOpen(true)}>Reset password</button>
  return (
    <form className="inline-form" onSubmit={submit}>
      <input type="password" autoComplete="new-password" aria-label={`New password for ${user.name}`}
        placeholder="New password" minLength={10} required autoFocus value={password}
        onChange={(e) => setPassword(e.target.value)} />
      <button className="primary">Set</button>
      <button type="button" onClick={() => setOpen(false)}>Cancel</button>
    </form>
  )
}

export default function UsersPage() {
  const { me } = useAuth()
  const { data, error, reload } = useLoad(useCallback(() => api.GET('/api/users'), []))
  const reps = useLoad(useCallback(() => api.GET('/api/reps'), []))
  const unlinked = (data ?? []).filter((u) => u.role === 'user' && u.active && !u.rep_id).length

  return (
    <section>
      <h1>Users</h1>
      <p className="lede">
        Admins can change everything here. Users view the board, and Reports and Deals for the rep they're linked
        to — pick that rep when you add them (several users can share one rep). Admins see everything.
        After 5 wrong passwords an account locks for 15 minutes; unlock it early or reset the password here.
      </p>
      {unlinked > 0 && (
        <p className="banner warn" role="status">
          {unlinked} user{unlinked === 1 ? ' isn’t' : 's aren’t'} linked to a rep yet and can't see any reports.
          Edit {unlinked === 1 ? 'them' : 'each one'} and pick a rep.
        </p>
      )}
      {error ? <p className="form-error">{errorMessage(error)}</p> : null}
      <CrudTable<User>
        rows={data ?? []}
        fields={fields(reps.data ?? [])}
        addLabel="Add user"
        rowClass={(u) => (u.active ? undefined : 'inactive')}
        search={(u, q) => `${u.name} ${u.email}`.toLowerCase().includes(q)}
        onCreate={async (v) => {
          const { error } = await api.POST('/api/users', {
            body: {
              name: String(v.name), email: String(v.email), role: v.role as User['role'], password: String(v.password),
              rep_id: repIdOf(v),
            },
          })
          if (!error) await reload()
          return error ? errorMessage(error) : null
        }}
        onUpdate={async (u, v) => {
          const { error } = await api.PATCH('/api/users/{user_id}', {
            params: { path: { user_id: u.id } },
            body: {
              name: String(v.name), email: String(v.email), role: v.role as User['role'], active: Boolean(v.active),
              rep_id: repIdOf(v),
            },
          })
          await reload()
          return error ? errorMessage(error) : null
        }}
        onDelete={async (u) => {
          const { error } = await api.DELETE('/api/users/{user_id}', { params: { path: { user_id: u.id } } })
          await reload()
          return error ? errorMessage(error) : null
        }}
        deleteConfirm={(u) => `Delete ${u.name}? Users with history can only be deactivated.`}
        actions={(u, setError) => (
          <>
            {isLocked(u) && (
              <button onClick={async () => {
                const { error } = await api.POST('/api/users/{user_id}/unlock', { params: { path: { user_id: u.id } } })
                setError(error ? errorMessage(error) : null)
                await reload()
              }}>Unlock</button>
            )}
            {u.id !== me?.user_id && <ResetPassword user={u} onError={setError} />}
          </>
        )}
      />
    </section>
  )
}
