import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { api, errorMessage, type Rep } from '../../api/client'
import { monthLabel } from '../../lib/format'
import { useLoad } from '../../lib/useLoad'

type Row = { rep_id: number; name: string; quota: string }

export default function QuotasPage() {
  const periods = useLoad(useCallback(() => api.GET('/api/periods'), []))
  const reps = useLoad(useCallback(() => api.GET('/api/reps'), []))
  const [params] = useSearchParams()
  const [periodId, setPeriodId] = useState<number | null>(params.get('period') ? Number(params.get('period')) : null)
  const [rows, setRows] = useState<Row[] | null>(null)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [dirty, setDirty] = useState(false)

  // Default to the current month (newest unlocked), matching the board.
  const selectedId = periodId ?? (periods.data?.find((p) => !p.locked_at) ?? periods.data?.[0])?.id ?? null
  const period = periods.data?.find((p) => p.id === selectedId)
  const locked = !!period?.locked_at

  useEffect(() => {
    if (selectedId == null) return
    let cancelled = false
    api.GET('/api/periods/{period_id}/reps', { params: { path: { period_id: selectedId } } }).then(({ data, error }) => {
      if (cancelled) return
      setRows(data ? data.map((r) => ({ rep_id: r.rep_id, name: r.name, quota: r.quota == null ? '' : String(r.quota) })) : [])
      setMessage(error ? { kind: 'error', text: errorMessage(error) } : null)
      setDirty(false)
    })
    return () => { cancelled = true }
  }, [selectedId])

  function update(next: Row[]) {
    setRows(next)
    setDirty(true)
    setMessage(null)
  }

  function move(index: number, delta: number) {
    if (!rows) return
    const next = [...rows]
    const [row] = next.splice(index, 1)
    next.splice(index + delta, 0, row)
    update(next)
  }

  async function save() {
    if (!rows || selectedId == null) return
    const { data, error } = await api.PUT('/api/periods/{period_id}/reps', {
      params: { path: { period_id: selectedId } },
      body: rows.map((r) => ({ rep_id: r.rep_id, quota: r.quota.trim() === '' ? null : Number(r.quota) })),
    })
    if (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
      return
    }
    setRows(data.map((r) => ({ rep_id: r.rep_id, name: r.name, quota: r.quota == null ? '' : String(r.quota) })))
    setDirty(false)
    setMessage({ kind: 'ok', text: 'Saved. The board will pick this up on its next refresh.' })
  }

  const onBoard = new Set(rows?.map((r) => r.rep_id))
  const available = (reps.data ?? []).filter((r: Rep) => r.active && !onBoard.has(r.id))

  return (
    <section>
      <h1>Quotas</h1>
      <p className="lede">
        Which reps appear on a month's board, in what order, and their quota. Leave quota blank for no quota
        (shown as “~”, like HOUSE).
      </p>

      <div className="crud-toolbar">
        <label className="inline-label">
          Month
          <select value={selectedId ?? ''} onChange={(e) => setPeriodId(Number(e.target.value))}>
            {periods.data?.map((p) => (
              <option key={p.id} value={p.id}>{monthLabel(p)}{p.locked_at ? ' (locked)' : ''}</option>
            ))}
          </select>
        </label>
      </div>

      {locked && <p className="banner">This month is locked, so its quotas are read-only.</p>}
      {message && <p className={message.kind === 'ok' ? 'form-ok' : 'form-error'} role="status">{message.text}</p>}

      {rows && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Order</th><th>Rep</th><th>Quota</th><th className="actions-col"><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={4} className="muted">No reps on this month's board.</td></tr>}
              {rows.map((r, i) => (
                <tr key={r.rep_id}>
                  <td data-label="Order">
                    <div className="row-actions order-actions">
                      <button aria-label={`Move ${r.name} up`} disabled={locked || i === 0} onClick={() => move(i, -1)}>↑</button>
                      <button aria-label={`Move ${r.name} down`} disabled={locked || i === rows.length - 1} onClick={() => move(i, 1)}>↓</button>
                    </div>
                  </td>
                  <td data-label="Rep"><strong>{r.name}</strong></td>
                  <td data-label="Quota">
                    <input type="number" min={0} step="any" inputMode="decimal" className="quota-input" placeholder="~"
                      aria-label={`Quota for ${r.name}`} disabled={locked} value={r.quota}
                      onChange={(e) => update(rows.map((x) => (x.rep_id === r.rep_id ? { ...x, quota: e.target.value } : x)))} />
                  </td>
                  <td className="actions-col">
                    <button className="danger" disabled={locked}
                      onClick={() => update(rows.filter((x) => x.rep_id !== r.rep_id))}>Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {rows && !locked && (
        <div className="crud-toolbar">
          {available.length > 0 && (
            <select aria-label="Add rep to this month" value="" onChange={(e) => {
              const rep = available.find((r) => r.id === Number(e.target.value))
              if (rep) update([...rows, { rep_id: rep.id, name: rep.name, quota: '' }])
            }}>
              <option value="">Add rep to this month…</option>
              {available.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          )}
          <button className="primary" disabled={!dirty} onClick={save}>Save changes</button>
        </div>
      )}
    </section>
  )
}
