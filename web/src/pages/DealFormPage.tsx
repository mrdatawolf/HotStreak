import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { api, errorMessage, type Deal } from '../api/client'
import Combobox from '../components/Combobox'
import { money, monthLabel } from '../lib/format'
import { centsToInput, parseMoney } from '../lib/money'
import { useLoad } from '../lib/useLoad'

type Line = { key: number; itemId: number | null; text: string; qty: string; amount: string }
type ClientChoice = { id: number | null; text: string; location: string; isNew: boolean }

let nextKey = 1
const blankLine = (): Line => ({ key: nextKey++, itemId: null, text: '', qty: '1', amount: '' })

const pad = (n: number) => String(n).padStart(2, '0')
const isoDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

function monthBounds(year: number, month: number) {
  const last = new Date(year, month, 0).getDate()
  return { min: `${year}-${pad(month)}-01`, max: `${year}-${pad(month)}-${pad(last)}` }
}

/** Only allow in-app return paths. */
function safeReturn(path: string | null, fallback: string) {
  return path && path.startsWith('/') && !path.startsWith('//') ? path : fallback
}

export default function DealFormPage() {
  const { dealId } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const editingId = dealId ? Number(dealId) : null

  const periods = useLoad(useCallback(() => api.GET('/api/periods'), []))
  const reps = useLoad(useCallback(() => api.GET('/api/reps'), []))
  const clients = useLoad(useCallback(() => api.GET('/api/clients', { params: { query: { limit: 1000 } } }), []))
  const items = useLoad(useCallback(() => api.GET('/api/items', { params: { query: { limit: 1000 } } }), []))
  const flags = useLoad(useCallback(() => api.GET('/api/flags'), []))

  const [existing, setExisting] = useState<Deal | null>(null)
  const [chosenPeriodId, setPeriodId] = useState<number | null>(params.get('period') ? Number(params.get('period')) : null)
  const [repId, setRepId] = useState<number | null>(params.get('rep') ? Number(params.get('rep')) : null)
  const [boardRepIds, setBoardRepIds] = useState<number[]>([])
  const [client, setClient] = useState<ClientChoice>({ id: null, text: '', location: '', isNew: false })
  // null = not touched yet, so the default below applies.
  const [chosenDate, setDate] = useState<string | null>(null)
  const [lines, setLines] = useState<Line[]>([blankLine()])
  const [total, setTotal] = useState('')
  const [totalManual, setTotalManual] = useState(false)
  const [flagIds, setFlagIds] = useState<number[]>([])
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Load the deal being edited.
  useEffect(() => {
    if (editingId == null) return
    api.GET('/api/deals/{deal_id}', { params: { path: { deal_id: editingId } } }).then(({ data, error }) => {
      if (!data) {
        setError(errorMessage(error, 'Deal not found'))
        return
      }
      setExisting(data)
      setPeriodId(data.period_id)
      setRepId(data.rep_id)
      setClient({ id: data.client.id, text: data.client.name, location: data.client.location ?? '', isNew: false })
      setDate(data.deal_date ?? '')
      setLines(data.lines.map((l) => ({
        key: nextKey++, itemId: l.item_id, text: l.label, qty: String(l.qty), amount: centsToInput(l.amount_cents),
      })))
      const lineSum = data.lines.every((l) => l.amount_cents != null)
        ? data.lines.reduce((s, l) => s + (l.amount_cents ?? 0), 0) : null
      setTotal(centsToInput(data.total_cents))
      setTotalManual(lineSum !== data.total_cents)
      setFlagIds(data.flags.map((f) => f.id))
      setNotes(data.notes ?? '')
    })
  }, [editingId])

  // New deals default to the current month (newest unlocked), like the board.
  const currentPeriod = periods.data?.find((p) => !p.locked_at) ?? periods.data?.[0]
  const periodId = chosenPeriodId ?? currentPeriod?.id ?? null
  const period = periods.data?.find((p) => p.id === periodId)

  // Reps on that month's board are listed first, in board order.
  useEffect(() => {
    if (periodId == null) return
    api.GET('/api/periods/{period_id}/reps', { params: { path: { period_id: periodId } } })
      .then(({ data }) => setBoardRepIds(data?.map((r) => r.rep_id) ?? []))
  }, [periodId])

  // New deals default to today when today falls in the chosen month.
  const [today] = useState(() => new Date())
  const todayFits = !!period && today.getFullYear() === period.year && today.getMonth() + 1 === period.month
  const date = chosenDate ?? (editingId == null && todayFits ? isoDay(today) : '')

  const fromSheet = existing?.sheet_ref
  // Sheet deals are overwritten by the next sync, so they're changed on the sheet, not here.
  const locked = !!existing?.period_locked || !!fromSheet
  const bounds = period ? monthBounds(period.year, period.month) : undefined

  const lineCents = lines.map((l) => parseMoney(l.amount))
  const lineSum = lineCents.every((c) => c != null && !Number.isNaN(c))
    ? lineCents.reduce<number>((s, c) => s + (c ?? 0), 0) : null
  const shownTotal = totalManual ? total : lineSum != null ? centsToInput(lineSum) : ''

  const repOptions = useMemo(() => {
    const all = reps.data ?? []
    const onBoard = boardRepIds.map((id) => all.find((r) => r.id === id)).filter((r) => r != null)
    const others = all.filter((r) => !boardRepIds.includes(r.id) && (r.active || r.id === repId))
    return { onBoard, others }
  }, [reps.data, boardRepIds, repId])

  const clientOptions = useMemo(
    () => (clients.data ?? []).map((c) => ({ id: c.id, label: c.name, detail: c.location })), [clients.data])
  const itemOptions = useMemo(
    () => (items.data ?? []).map((i) => ({ id: i.id, label: [i.brand, i.model].filter(Boolean).join(' '), detail: i.category })),
    [items.data])

  function updateLine(key: number, patch: Partial<Line>) {
    setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (periodId == null || repId == null) return setError('Pick a month and a rep')
    if (client.id == null && !client.isNew) return setError('Pick a client from the list, or choose “+ New client”')
    if (lineCents.some((c) => Number.isNaN(c))) return setError('Check the line amounts — use numbers like 1234.56')
    const totalCents = totalManual ? parseMoney(total) : null
    if (totalManual && (totalCents == null || Number.isNaN(totalCents))) return setError('Enter the deal total')
    if (!totalManual && lineSum == null) return setError('Enter an amount on every line, or type the total')

    const body = {
      period_id: periodId,
      rep_id: repId,
      ...(client.isNew
        ? { new_client: { name: client.text.trim(), location: client.location.trim() || null } }
        : { client_id: client.id }),
      deal_date: date || null,
      total_cents: totalManual ? totalCents : null,
      notes: notes.trim() || null,
      flag_ids: flagIds,
      lines: lines.map((l, i) => ({
        item_id: l.itemId,
        description: l.itemId == null ? l.text.trim() || null : null,
        qty: Math.max(1, Number(l.qty) || 1),
        amount_cents: lineCents[i],
      })),
    }
    setBusy(true)
    const res = editingId == null
      ? await api.POST('/api/deals', { body })
      : await api.PUT('/api/deals/{deal_id}', { params: { path: { deal_id: editingId } }, body })
    setBusy(false)
    if (res.error) return setError(errorMessage(res.error))
    navigate(safeReturn(params.get('return'), `/deals?period=${periodId}`))
  }

  async function remove() {
    if (editingId == null || !confirm('Delete this deal?')) return
    const { error } = await api.DELETE('/api/deals/{deal_id}', { params: { path: { deal_id: editingId } } })
    if (error) return setError(errorMessage(error))
    navigate(safeReturn(params.get('return'), `/deals?period=${periodId}`))
  }

  const back = safeReturn(params.get('return'), `/deals${periodId ? `?period=${periodId}` : ''}`)

  return (
    <section>
      <p className="crumb"><Link to={back}>← Back</Link></p>
      <h1>{editingId == null ? 'New deal' : 'Edit deal'}</h1>
      {existing && (
        <p className="lede">
          Entered by {existing.created_by_name ?? '—'} · last changed by {existing.updated_by_name ?? '—'}
          {' '}on {new Date(existing.updated_at + 'Z').toLocaleString()}
        </p>
      )}
      {fromSheet
        ? <p className="banner">
            This deal comes from the Google Sheet (cell {fromSheet}){existing?.sheet_plus ? ', marked “+”' : ''}.
            Change it on the sheet; the next sync brings it in.
          </p>
        : locked && <p className="banner">{monthLabel(period!)} is locked, so this deal is read-only.</p>}

      <form className="panel deal-form" onSubmit={submit}>
        <fieldset disabled={locked || busy}>
          <div className="form-grid">
            <label>
              Month
              <select required value={periodId ?? ''} onChange={(e) => {
                const next = periods.data?.find((p) => p.id === Number(e.target.value))
                if (next && !date.startsWith(`${next.year}-${pad(next.month)}-`)) setDate('')
                setPeriodId(Number(e.target.value))
              }}>
                {periods.data?.filter((p) => !p.locked_at || p.id === periodId).map((p) => (
                  <option key={p.id} value={p.id}>{monthLabel(p)}{p.locked_at ? ' (locked)' : ''}</option>
                ))}
              </select>
            </label>
            <label>
              Rep
              <select required value={repId ?? ''} onChange={(e) => setRepId(Number(e.target.value))}>
                <option value="" disabled>Choose…</option>
                {repOptions.onBoard.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                {repOptions.others.length > 0 && (
                  <optgroup label="Not on this month's board">
                    {repOptions.others.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                  </optgroup>
                )}
              </select>
            </label>
            <label>
              Date
              <input type="date" value={date} min={bounds?.min} max={bounds?.max} onChange={(e) => setDate(e.target.value)} />
            </label>
          </div>

          <div className="form-grid">
            <div className="field">
              <span className="field-label">Client</span>
              <Combobox
                label="Client"
                required
                value={client.text}
                options={clientOptions}
                placeholder="Search clients…"
                onType={(text) => setClient({ id: null, text, location: '', isNew: false })}
                onPick={(o) => setClient({ id: o.id, text: o.label, location: o.detail ?? '', isNew: false })}
                createLabel={(text) => `+ New client “${text}”`}
                onCreate={(text) => setClient({ id: null, text, location: '', isNew: true })}
              />
              {client.id != null && client.location && <span className="hint">Location: {client.location}</span>}
            </div>
            {client.isNew && (
              <label>
                <span>Location / branch <span className="muted">(optional)</span></span>
                <input value={client.location} placeholder="e.g. Eureka"
                  onChange={(e) => setClient({ ...client, location: e.target.value })} />
              </label>
            )}
          </div>
          {client.isNew && <p className="hint">A new client “{client.text}” will be added when you save.</p>}

          <div className="lines">
            <div className="lines-head" aria-hidden="true">
              <span>Item</span><span>Qty</span><span>Amount</span><span />
            </div>
            {lines.map((l, i) => (
              <div className="line" key={l.key}>
                <Combobox
                  label={`Item ${i + 1}`}
                  required
                  value={l.text}
                  options={itemOptions}
                  placeholder="Search items, or type anything (e.g. Various)"
                  onType={(text) => updateLine(l.key, { text, itemId: null })}
                  onPick={(o) => updateLine(l.key, { text: o.label, itemId: o.id })}
                />
                <input aria-label={`Quantity ${i + 1}`} type="number" min={1} step={1} inputMode="numeric" required
                  value={l.qty} onChange={(e) => updateLine(l.key, { qty: e.target.value })} />
                <input aria-label={`Amount ${i + 1}`} inputMode="decimal" placeholder="$0.00" value={l.amount}
                  onChange={(e) => updateLine(l.key, { amount: e.target.value })} />
                <button type="button" className="danger" aria-label={`Remove item ${i + 1}`} disabled={lines.length === 1}
                  onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}>✕</button>
              </div>
            ))}
            <button type="button" onClick={() => setLines((ls) => [...ls, blankLine()])}>+ Add another item</button>
          </div>

          <div className="form-grid">
            <label>
              Deal total
              <input inputMode="decimal" placeholder="$0.00" value={shownTotal}
                onChange={(e) => { setTotal(e.target.value); setTotalManual(true) }} />
              <span className="hint">
                {totalManual
                  ? <>Typed by hand. {lineSum != null && (
                    <button type="button" className="link" onClick={() => setTotalManual(false)}>
                      Use line amounts ({money(lineSum)})
                    </button>)}</>
                  : 'Adds up the line amounts. Type here to override.'}
              </span>
            </label>
          </div>

          {flags.data && flags.data.length > 0 && (
            <fieldset className="flags">
              <legend>Flags</legend>
              {flags.data.map((f) => (
                <label key={f.id} className="check">
                  <input type="checkbox" checked={flagIds.includes(f.id)}
                    onChange={(e) => setFlagIds((ids) => (e.target.checked ? [...ids, f.id] : ids.filter((x) => x !== f.id)))} />
                  <span className="swatch" style={{ background: f.color }} />
                  {f.name}
                </label>
              ))}
            </fieldset>
          )}

          <label className="notes">
            <span>Notes <span className="muted">(optional)</span></span>
            <textarea rows={3} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
        </fieldset>

        {error && <p className="form-error" role="alert">{error}</p>}

        {!locked && (
          <div className="form-actions">
            <button className="primary" disabled={busy}>{busy ? 'Saving…' : editingId == null ? 'Add deal' : 'Save changes'}</button>
            <Link to={back}>Cancel</Link>
            {editingId != null && <button type="button" className="danger push-right" onClick={remove}>Delete deal</button>}
          </div>
        )}
      </form>
    </section>
  )
}
