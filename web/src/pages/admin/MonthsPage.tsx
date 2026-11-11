import { useCallback, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api, errorMessage, type PeriodSummary } from '../../api/client'
import { money, monthLabel } from '../../lib/format'
import { useLoad } from '../../lib/useLoad'

function nextMonth(p?: PeriodSummary) {
  if (!p) {
    const now = new Date()
    return { year: now.getFullYear(), month: now.getMonth() + 1 }
  }
  return p.month === 12 ? { year: p.year + 1, month: 1 } : { year: p.year, month: p.month + 1 }
}

export default function MonthsPage() {
  const { data, error, reload } = useLoad(useCallback(() => api.GET('/api/periods/summary'), []))
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [other, setOther] = useState('')

  const upcoming = nextMonth(data?.[0])

  async function act(call: () => Promise<{ error?: unknown }>, ok: string) {
    const { error } = await call()
    setMessage(error ? { kind: 'error', text: errorMessage(error) } : { kind: 'ok', text: ok })
    await reload()
  }

  function startOther(e: FormEvent) {
    e.preventDefault()
    const [year, month] = other.split('-').map(Number)
    void act(() => api.POST('/api/periods', { body: { year, month } }), `Started ${monthLabel({ year, month })}.`)
  }

  return (
    <section>
      <h1>Months</h1>
      <p className="lede">
        Each month is its own board, like the monthly tabs on the old sheet. Starting a month copies the reps, their
        order, and quotas from the month before. Locking a month makes its deals and quotas read-only; the board's
        “current month” is the newest unlocked one.
      </p>

      <div className="crud-toolbar">
        <button className="primary" onClick={() => act(() => api.POST('/api/periods'), `Started ${monthLabel(upcoming)}.`)}>
          Start {monthLabel(upcoming)}
        </button>
        <form className="inline-form" onSubmit={startOther}>
          <label className="inline-label">
            Or start a specific month
            <input type="month" required value={other} onChange={(e) => setOther(e.target.value)} />
          </label>
          <button>Start</button>
        </form>
      </div>

      {error ? <p className="form-error">{errorMessage(error)}</p> : null}
      {message && <p className={message.kind === 'ok' ? 'form-ok' : 'form-error'} role="status">{message.text}</p>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Month</th><th>Status</th><th className="num">Reps</th><th className="num">Deals</th>
              <th className="num">Total</th><th className="actions-col"><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {data?.length === 0 && <tr><td colSpan={6} className="muted">No months yet.</td></tr>}
            {data?.map((p) => (
              <tr key={p.id}>
                <td data-label="Month"><strong>{monthLabel(p)}</strong></td>
                <td data-label="Status">
                  {p.locked_at
                    ? <span className="muted">Locked {new Date(p.locked_at + 'Z').toLocaleDateString()}{p.locked_by_name ? ` by ${p.locked_by_name}` : ''}</span>
                    : <span className="badge open">Open</span>}
                </td>
                <td data-label="Reps" className="num">{p.rep_count}</td>
                <td data-label="Deals" className="num">{p.deal_count}</td>
                <td data-label="Total" className="num">{money(p.total_sales_cents)}</td>
                <td className="actions-col">
                  <div className="row-actions">
                    <Link to={`/board/${p.id}`}>Board</Link>
                    <Link to={`/deals?period=${p.id}`}>Deals</Link>
                    {!p.locked_at && <Link to={`/admin/quotas?period=${p.id}`}>Quotas</Link>}
                    {p.locked_at ? (
                      <button onClick={() => confirm(`Unlock ${monthLabel(p)}? Its deals and quotas become editable again.`)
                        && act(() => api.POST('/api/periods/{period_id}/unlock', { params: { path: { period_id: p.id } } }),
                          `Unlocked ${monthLabel(p)}.`)}>Unlock</button>
                    ) : (
                      <button onClick={() => confirm(`Lock ${monthLabel(p)}? Its deals and quotas become read-only.`)
                        && act(() => api.POST('/api/periods/{period_id}/lock', { params: { path: { period_id: p.id } } }),
                          `Locked ${monthLabel(p)}.`)}>Lock</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
