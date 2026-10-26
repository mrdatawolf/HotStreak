import { useState, type FormEvent, type ReactNode } from 'react'

export type Values = Record<string, string | boolean>

export type Field = {
  key: string
  label: string
  type?: 'text' | 'email' | 'password' | 'select' | 'checkbox' | 'color'
  options?: readonly { value: string; label: string }[]
  placeholder?: string
  required?: boolean
  /** Only asked for when adding (e.g. an initial password). */
  createOnly?: boolean
  /** Shown in the table but never edited. */
  readOnly?: boolean
  /** Custom read-only cell. Checkbox fields always toggle straight from the table. */
  render?: (row: never) => ReactNode
}

/** Returns an error message, or null on success. */
type Save = (values: Values) => Promise<string | null>

type Props<T extends { id: number }> = {
  rows: T[]
  fields: Field[]
  addLabel: string
  onCreate: Save
  onUpdate: (row: T, values: Values) => Promise<string | null>
  onDelete?: (row: T) => Promise<string | null>
  deleteConfirm?: (row: T) => string
  actions?: (row: T, setError: (e: string | null) => void) => ReactNode
  rowClass?: (row: T) => string | undefined
  search?: (row: T, q: string) => boolean
}

function valuesOf(fields: Field[], row?: Record<string, unknown>): Values {
  return Object.fromEntries(
    fields.map((f) => {
      const v = row?.[f.key]
      if (f.type === 'checkbox') return [f.key, row ? Boolean(v) : true]
      if (f.type === 'select') return [f.key, (v as string) ?? f.options?.[0]?.value ?? '']
      if (f.type === 'color') return [f.key, (v as string) ?? '#22c55e']
      return [f.key, (v as string | null) ?? '']
    }),
  )
}

type InputProps = { field: Field; value: string | boolean; onChange: (v: string | boolean) => void; form?: string }

function Input({ field, value, onChange, form }: InputProps) {
  // `form` ties inputs in other table cells to the row's form, so Enter and `required` work.
  const common = { 'aria-label': field.label, required: field.required, form }
  if (field.type === 'checkbox') {
    return <input type="checkbox" {...common} required={false} checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
  }
  if (field.type === 'select') {
    return (
      <select {...common} value={String(value)} onChange={(e) => onChange(e.target.value)}>
        {field.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    )
  }
  return (
    <input
      {...common}
      type={field.type ?? 'text'}
      placeholder={field.placeholder}
      autoComplete={field.type === 'password' ? 'new-password' : 'off'}
      value={String(value)}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

function display(field: Field, row: Record<string, unknown>) {
  if (field.render) return field.render(row as never)
  const v = row[field.key]
  if (field.type === 'select') return field.options?.find((o) => o.value === v)?.label ?? String(v ?? '')
  if (field.type === 'color') {
    return <span className="swatch-label"><span className="swatch" style={{ background: String(v) }} />{String(v)}</span>
  }
  return v == null || v === '' ? <span className="muted">—</span> : String(v)
}

export default function CrudTable<T extends { id: number }>(props: Props<T>) {
  const { rows, fields, addLabel, onCreate, onUpdate, onDelete, deleteConfirm, actions, rowClass, search } = props
  const editFields = fields.filter((f) => !f.createOnly)
  const [adding, setAdding] = useState<Values | null>(null)
  const [editing, setEditing] = useState<{ id: number; values: Values } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [q, setQ] = useState('')
  // Checkbox values shown while their save is in flight, so toggles feel instant; cleared (reverting on error) after.
  const [pending, setPending] = useState<Record<string, boolean>>({})

  async function toggle(row: T, record: Record<string, unknown>, key: string, checked: boolean) {
    const id = `${row.id}:${key}`
    setPending((p) => ({ ...p, [id]: checked }))
    await run(() => onUpdate(row, { ...valuesOf(editFields, record), [key]: checked }), () => {})
    setPending((p) => {
      const next = { ...p }
      delete next[id]
      return next
    })
  }

  async function run(action: () => Promise<string | null>, onOk: () => void) {
    setBusy(true)
    const err = await action()
    setBusy(false)
    setError(err)
    if (!err) onOk()
  }

  function submitAdd(e: FormEvent) {
    e.preventDefault()
    if (adding) void run(() => onCreate(adding), () => setAdding(null))
  }

  function submitEdit(e: FormEvent, row: T) {
    e.preventDefault()
    if (editing) void run(() => onUpdate(row, editing.values), () => setEditing(null))
  }

  const shown = search && q ? rows.filter((r) => search(r, q.toLowerCase())) : rows

  return (
    <div className="crud">
      <div className="crud-toolbar">
        {search && <input type="search" placeholder="Search…" aria-label="Search" value={q} onChange={(e) => setQ(e.target.value)} />}
        {!adding && <button className="primary" onClick={() => { setAdding(valuesOf(fields)); setError(null) }}>{addLabel}</button>}
      </div>

      {adding && (
        <form className="panel crud-add" onSubmit={submitAdd}>
          {fields.filter((f) => !f.readOnly).map((f) => (
            <label key={f.key} className={f.type === 'checkbox' ? 'check' : undefined}>
              <span>{f.label}</span>
              <Input field={f} value={adding[f.key]} onChange={(v) => setAdding({ ...adding, [f.key]: v })} />
            </label>
          ))}
          <div className="crud-add-actions">
            <button className="primary" disabled={busy}>Save</button>
            <button type="button" onClick={() => { setAdding(null); setError(null) }}>Cancel</button>
          </div>
        </form>
      )}

      {error && <p className="form-error" role="alert">{error}</p>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {editFields.map((f) => <th key={f.key}>{f.label}</th>)}
              <th className="actions-col"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr><td colSpan={editFields.length + 1} className="muted">Nothing here yet.</td></tr>
            )}
            {shown.map((row) => {
              const record = row as unknown as Record<string, unknown>
              const isEditing = editing?.id === row.id
              const formId = `edit-${row.id}`
              return (
                <tr key={row.id} className={rowClass?.(row)}>
                  {editFields.map((f) => (
                    <td key={f.key} data-label={f.label}>
                      {f.readOnly ? display(f, record) : isEditing && f.type !== 'checkbox' ? (
                        <Input field={f} form={formId} value={editing.values[f.key]}
                          onChange={(v) => setEditing({ id: row.id, values: { ...editing.values, [f.key]: v } })} />
                      ) : f.type === 'checkbox' ? (
                        <input type="checkbox" aria-label={f.label} disabled={busy}
                          checked={pending[`${row.id}:${f.key}`] ?? Boolean(record[f.key])}
                          onChange={(e) => void toggle(row, record, f.key, e.target.checked)} />
                      ) : display(f, record)}
                    </td>
                  ))}
                  <td className="actions-col">
                    {isEditing ? (
                      <form id={formId} className="row-actions" onSubmit={(e) => submitEdit(e, row)}>
                        <button className="primary" disabled={busy}>Save</button>
                        <button type="button" onClick={() => { setEditing(null); setError(null) }}>Cancel</button>
                      </form>
                    ) : (
                      <div className="row-actions">
                        <button onClick={() => { setEditing({ id: row.id, values: valuesOf(editFields, record) }); setError(null) }}>Edit</button>
                        {actions?.(row, setError)}
                        {onDelete && (
                          <button className="danger" disabled={busy} onClick={() => {
                            if (confirm(deleteConfirm?.(row) ?? 'Delete this?')) void run(() => onDelete(row), () => {})
                          }}>Delete</button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
