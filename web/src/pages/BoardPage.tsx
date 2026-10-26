import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useAuth } from '../auth/AuthContext'
import SettingsMenu from '../components/SettingsMenu'
import { api, type Board, type BoardDeal, type BoardRep, type Period } from '../api/client'
import { money, monthLabel, monthShort, percent, quotaLabel } from '../lib/format'

const REFRESH_MS = 30_000

async function loadBoard(periodId: number | null): Promise<Board> {
  let id = periodId
  if (id == null) {
    const { data, error } = await api.GET('/api/periods/current')
    if (error || !data) throw new Error('No current month')
    id = data.id
  }
  const { data, error } = await api.GET('/api/periods/{period_id}/board', {
    params: { path: { period_id: id } },
  })
  if (error || !data) throw new Error('Board not found')
  return data
}

export default function BoardPage() {
  const params = useParams()
  const navigate = useNavigate()
  const { me } = useAuth()
  const periodId = params.periodId ? Number(params.periodId) : null

  const [board, setBoard] = useState<Board | null>(null)
  const [periods, setPeriods] = useState<Period[]>([])
  const [error, setError] = useState<string | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)

  const refresh = useCallback(async () => {
    try {
      setBoard(await loadBoard(periodId))
      setUpdatedAt(new Date())
      setError(null)
    } catch (e) {
      // Keep showing the last good board; the TV shouldn't go blank on a blip.
      setError(e instanceof Error ? e.message : 'Could not reach the server')
    }
  }, [periodId])

  useEffect(() => {
    // State is only set after the fetch resolves, so this doesn't cascade renders.
    // oxlint-disable-next-line react/set-state-in-effect
    void refresh()
    const timer = setInterval(refresh, REFRESH_MS)
    return () => clearInterval(timer)
  }, [refresh])

  useEffect(() => {
    api.GET('/api/periods').then(({ data }) => data && setPeriods(data))
  }, [])

  // Left/right arrows step back/forward a month. periods is newest first.
  const shownId = board?.period.id
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return
      if (e.target instanceof HTMLElement && e.target.closest('input, select, textarea')) return
      const index = periods.findIndex((p) => p.id === shownId)
      const target = index === -1 ? undefined : periods[e.key === 'ArrowLeft' ? index + 1 : index - 1]
      if (!target) return
      e.preventDefault()
      // Same rule as the API: newest unlocked month, else newest.
      const current = periods.find((p) => !p.locked_at) ?? periods[0]
      // Landing on the current month returns to /board so the TV keeps following it.
      navigate(target.id === current.id ? '/board' : `/board/${target.id}`)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [periods, shownId, navigate])

  if (!board) {
    return <main className="board-status">{error ?? 'Loading…'}</main>
  }

  const canEdit = !!me && me.role !== 'board'
  const here = periodId == null ? '/board' : `/board/${periodId}`

  return (
    <main className="board">
      <header className="board-header">
        <h1>
          {monthLabel(board.period)}
          {board.period.locked_at && <span className="badge">Locked</span>}
        </h1>
        <p className="header-total">
          <span>Monthly total</span> {money(board.total_sales_cents)}
        </p>
        <div className="board-controls">
          <select
            aria-label="Month"
            value={periodId ?? ''}
            onChange={(e) => navigate(e.target.value ? `/board/${e.target.value}` : '/board')}
          >
            <option value="">Current month</option>
            {periods.map((p) => (
              <option key={p.id} value={p.id}>
                {monthShort(p)}
              </option>
            ))}
          </select>
          {canEdit && !board.period.locked_at && (
            <Link className="button primary" to={`/deals/new?period=${board.period.id}&return=${encodeURIComponent(here)}`}>
              Add deal
            </Link>
          )}
          {canEdit && <Link to="/deals">Deals</Link>}
          <Link to="/reports">Reports</Link>
          <SettingsMenu />
          <span className={error ? 'stale' : 'updated'}>
            {error ? `Offline — last update ${updatedAt?.toLocaleTimeString() ?? 'never'}` : `Updated ${updatedAt?.toLocaleTimeString()}`}
          </span>
        </div>
      </header>

      <div className="board-grid" role="table" aria-label="Sales by rep">
        <div className="board-row board-head" role="row">
          <span role="columnheader">Rep</span>
          <span role="columnheader">Deals</span>
          <span role="columnheader" className="num">Quota</span>
          <span role="columnheader" className="num">Sales</span>
        </div>
        {board.reps.map((rep) => (
          <RepRow key={rep.rep_id} rep={rep} dealHref={canEdit ? (id) => `/deals/${id}?return=${encodeURIComponent(here)}` : undefined} />
        ))}
        <div className="board-row board-total" role="row">
          <span role="rowheader">Monthly total</span>
          <span className="num sales" role="cell">{money(board.total_sales_cents)}</span>
        </div>
      </div>
    </main>
  )
}

type DealHref = (dealId: number) => string

function RepRow({ rep, dealHref }: { rep: BoardRep; dealHref?: DealHref }) {
  const pct = rep.pct_of_quota
  return (
    <div className="board-row" role="row">
      <span className="rep-name" role="rowheader">
        {rep.name}
        {!rep.counts_toward_total && <small>not in total</small>}
      </span>
      <div className="deals" role="cell">
        {rep.deals.length === 0 && <span className="no-deals">—</span>}
        {rep.deals.map((deal) => (
          <DealCard key={deal.id} deal={deal} href={dealHref?.(deal.id)} />
        ))}
      </div>
      <span className="num quota" role="cell">
        {quotaLabel(rep.quota)}
      </span>
      <div className="num sales-cell" role="cell">
        <span className="sales">{money(rep.sales_cents)}</span>
        {pct != null && (
          <div className="progress" title={`${percent(pct)} of quota`}>
            <div className={pct >= 1 ? 'bar met' : 'bar'} style={{ width: `${Math.min(pct, 1) * 100}%` }} />
            <span>{percent(pct)}</span>
          </div>
        )}
      </div>
    </div>
  )
}

function DealCard({ deal, href }: { deal: BoardDeal; href?: string }) {
  const flag = deal.flags[0]
  const card = (
    <article
      className={flag ? 'deal flagged' : 'deal'}
      style={flag ? { ['--flag' as string]: flag.color } : undefined}
      title={deal.flags.map((f) => f.name).join(', ') || undefined}
    >
      <h3>{deal.client_name}</h3>
      {deal.client_location && <p className="location">{deal.client_location}</p>}
      {deal.lines.map((line, i) => (
        <p key={i} className="item">
          {line.qty > 1 && `(${line.qty}) `}
          {line.label}
        </p>
      ))}
      <p className="amount">{money(deal.total_cents)}</p>
    </article>
  )
  // Signed-in users can open a deal to edit it; the TV display just shows it.
  return href ? <Link className="deal-link" to={href} aria-label={`Edit deal: ${deal.client_name}`}>{card}</Link> : card
}
