import { useCallback } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { api, errorMessage } from '../api/client'
import { money, monthLabel } from '../lib/format'
import { useLoad } from '../lib/useLoad'

export default function DealsPage() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const periods = useLoad(useCallback(() => api.GET('/api/periods'), []))
  const reps = useLoad(useCallback(() => api.GET('/api/reps'), []))

  const current = periods.data?.find((p) => !p.locked_at) ?? periods.data?.[0]
  const periodId = params.get('period') ? Number(params.get('period')) : current?.id
  const repId = params.get('rep') ? Number(params.get('rep')) : undefined
  const q = params.get('q') ?? ''
  const period = periods.data?.find((p) => p.id === periodId)

  const deals = useLoad(useCallback(
    () => (periodId == null
      ? Promise.resolve({ data: [] })
      : api.GET('/api/deals', { params: { query: { period_id: periodId, rep_id: repId } } })),
    [periodId, repId]))

  function setParam(key: string, value: string | undefined) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  const needle = q.trim().toLowerCase()
  const shown = (deals.data ?? []).filter((d) => !needle || [
    d.client.name, d.client.location, d.rep_name, d.notes, ...d.lines.map((l) => l.label),
  ].join(' ').toLowerCase().includes(needle))
  const total = shown.reduce((s, d) => s + d.total_cents, 0)
  const here = params.size ? `/deals?${params.toString()}` : '/deals'

  return (
    <section>
      <h1>Deals</h1>
      <div className="crud-toolbar">
        <label className="inline-label">
          Month
          <select value={periodId ?? ''} onChange={(e) => setParam('period', e.target.value)}>
            {periods.data?.map((p) => (
              <option key={p.id} value={p.id}>{monthLabel(p)}{p.locked_at ? ' (locked)' : ''}</option>
            ))}
          </select>
        </label>
        <label className="inline-label">
          Rep
          <select value={repId ?? ''} onChange={(e) => setParam('rep', e.target.value)}>
            <option value="">All reps</option>
            {reps.data?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </label>
        <input type="search" placeholder="Search client, item, notes…" aria-label="Search deals" value={q}
          onChange={(e) => setParam('q', e.target.value)} />
        {period && !period.locked_at && (
          <Link className="button primary"
            to={`/deals/new?period=${periodId}${repId ? `&rep=${repId}` : ''}&return=${encodeURIComponent(here)}`}>
            Add deal
          </Link>
        )}
      </div>

      {period?.locked_at && <p className="banner">{monthLabel(period)} is locked. Deals can be viewed but not changed.</p>}
      {deals.error ? <p className="form-error">{errorMessage(deals.error)}</p> : null}

      <p className="summary">
        {shown.length} deal{shown.length === 1 ? '' : 's'} · <strong>{money(total)}</strong>
        {repId || needle ? ' (filtered)' : ''}
      </p>

      <div className="table-wrap">
        <table className="deals-table">
          <thead>
            <tr><th>Date</th><th>Rep</th><th>Client</th><th title="Marked “+” on the sheet that month">+</th><th>Items</th><th className="num">Total</th><th>Entered by</th></tr>
          </thead>
          <tbody>
            {shown.length === 0 && <tr><td colSpan={7} className="muted">No deals{needle ? ' match' : ' yet'}.</td></tr>}
            {shown.map((d) => {
              const open = `/deals/${d.id}?return=${encodeURIComponent(here)}`
              return (
                <tr key={d.id} className="clickable" onClick={() => navigate(open)}>
                  <td data-label="Date">{d.deal_date ? new Date(d.deal_date + 'T00:00').toLocaleDateString() : '—'}</td>
                  <td data-label="Rep">{d.rep_name}</td>
                  <td data-label="Client">
                    <Link to={open} onClick={(e) => e.stopPropagation()}>{d.client.name}</Link>
                    {d.client.location && <span className="muted"> · {d.client.location}</span>}
                    {d.flags.map((f) => (
                      <span key={f.id} className="flag-chip" style={{ ['--flag' as string]: f.color }}>{f.name}</span>
                    ))}
                  </td>
                  <td data-label="Marked +">{d.sheet_plus ? '+' : ''}</td>
                  <td data-label="Items">
                    {d.lines.map((l) => `${l.qty > 1 ? `(${l.qty}) ` : ''}${l.label}`).join(', ')}
                  </td>
                  <td data-label="Total" className="num">{money(d.total_cents)}</td>
                  <td data-label="Entered by" className="muted">{d.created_by_name ?? (d.sheet_ref ? `Sheet ${d.sheet_ref}` : '—')}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
