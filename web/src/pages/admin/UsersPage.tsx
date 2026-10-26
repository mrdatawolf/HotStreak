import { useCallback, useState, type FormEvent } from 'react'
import { api, errorMessage, type User } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import CrudTable, { type Field } from '../../components/CrudTable'
import { useLoad } from '../../lib/useLoad'

const ROLES = [
  { value: 'user', label: 'User' },
  { value: 'admin', label: 'Admin' },
] as const

const isLocked = (u: User) => !!u.locked_until && new Date(u.locked_until + 'Z') > new Date()

const FIELDS: Field[] = [
  { key: 'name', label: 'Name', required: true },
  { key: 'email', label: 'Email', type: 'email', required: true },
  { key: 'role', label: 'Role', type: 'select', options: ROLES },
  { key: 'active', label: 'Active', type: 'checkbox' },
  { key: 'password', label: 'Password (10+ characters)', type: 'password', required: true, createOnly: true },
  {
    key: 'locked_until', label: 'Status', readOnly: true,
    render: (u: User) => (isLocked(u)
      ? <span className="badge warn">Locked until {new Date(u.locked_until + 'Z').toLocaleTimeString()}</span>
      : <span className="muted">OK</span>),
  },
]

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

  return (
    <section>
      <h1>Users</h1>
      <p className="lede">
        Admins can change everything here. Users can view the board and (soon) enter deals.
        After 5 wrong passwords an account locks for 15 minutes; unlock it early or reset the password here.
      </p>
      {error ? <p className="form-error">{errorMessage(error)}</p> : null}
      <CrudTable<User>
        rows={data ?? []}
        fields={FIELDS}
        addLabel="Add user"
        rowClass={(u) => (u.active ? undefined : 'inactive')}
        search={(u, q) => `${u.name} ${u.email}`.toLowerCase().includes(q)}
        onCreate={async (v) => {
          const { error } = await api.POST('/api/users', {
            body: { name: String(v.name), email: String(v.email), role: v.role as User['role'], password: String(v.password) },
          })
          if (!error) await reload()
          return error ? errorMessage(error) : null
        }}
        onUpdate={async (u, v) => {
          const { error } = await api.PATCH('/api/users/{user_id}', {
            params: { path: { user_id: u.id } },
            body: { name: String(v.name), email: String(v.email), role: v.role as User['role'], active: Boolean(v.active) },
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
