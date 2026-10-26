import { useCallback, useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation, useSearchParams } from 'react-router'
import { api, errorMessage, type Item, type Report } from '../../api/client'
import { useLoad } from '../../lib/useLoad'
import { itemLabel, long, NO_BRAND, REPORT_PAGES, ym, type ReportContext } from './shared'

const REFRESH_MS = 5 * 60_000

const PRESETS = [
  ['last12', 'Last 12 months'],
  ['this-year', 'This year'],
  ['last-year', 'Last year'],
  ['last24', 'Last 24 months'],
  ['all', 'All time'],
  ['custom', 'Custom…'],
] as const

/** Filters and data shared by every report page; the filters live in the URL so they carry across pages. */
export default function ReportsLayout() {
  const [params, setParams] = useSearchParams()
  const { pathname } = useLocation()
  const periods = useLoad(useCallback(() => api.GET('/api/periods'), []))
  const reps = useLoad(useCallback(() => api.GET('/api/reps'), []))
  const catalog = useLoad(useCallback(() => api.GET('/api/items', { params: { query: { limit: 1000 } } }), []))

  const preset = params.get('range') ?? 'last12'
  const repId = params.get('rep') ? Number(params.get('rep')) : undefined
  const brand = params.get('brand') ?? undefined
  const itemId = params.get('item') ? Number(params.get('item')) : undefined

  const items = useMemo(() => catalog.data ?? [], [catalog.data])
  const brands = useMemo(() => {
    const named = [...new Set(items.map((i) => i.brand).filter((b): b is string => !!b))].sort((a, b) => a.localeCompare(b))
    return items.some((i) => !i.brand) ? [...named, NO_BRAND] : named
  }, [items])
  // Models for the Model filter: just the chosen brand's, when one is picked.
  const models = useMemo(() => items
    .filter((i) => brand === undefined || (brand === NO_BRAND ? !i.brand : i.brand === brand))
    .sort((a, b) => itemLabel(a).localeCompare(itemLabel(b))), [items, brand])
  const byLabel = useMemo(() => new Map(items.map((i) => [itemLabel(i), i])), [items])
  const current = periods.data?.find((p) => !p.locked_at) ?? periods.data?.[0]
  const first = periods.data?.[periods.data.length - 1]

  // Work out the month range for the chosen preset.
  let start: string | undefined
  let end: string | undefined
  if (current) {
    const endIdx = current.year * 12 + current.month - 1
    const at = (i: number) => ym(Math.floor(i / 12), (i % 12) + 1)
    end = at(endIdx)
    if (preset === 'last12') start = at(endIdx - 11)
    if (preset === 'last24') start = at(endIdx - 23)
    if (preset === 'this-year') start = ym(current.year, 1)
    if (preset === 'last-year') { start = ym(current.year - 1, 1); end = ym(current.year - 1, 12) }
    if (preset === 'all' && first) start = ym(first.year, first.month)
    if (preset === 'custom') { start = params.get('start') ?? at(endIdx - 11); end = params.get('end') ?? end }
  }

  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Bumped every few minutes so a display left on this page stays current.
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), REFRESH_MS)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!start || !end) return
    let cancelled = false
    // oxlint-disable-next-line react/set-state-in-effect -- marks the refetch; the previous chart stays up, dimmed
    setLoading(true)
    api.GET('/api/reports', { params: { query: { start, end, rep_id: repId, brand, item_id: itemId } } }).then(({ data, error }) => {
      if (cancelled) return
      if (data) setReport(data)
      setError(data ? null : errorMessage(error))
      setLoading(false)
    })
    return () => { cancelled = true }
  }, [start, end, repId, brand, itemId, tick])

  function setParam(key: string, value: string | undefined, also: Record<string, string | undefined> = {}) {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries({ [key]: value, ...also })) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    setParams(next, { replace: true })
  }

  // Changing brand drops a model from another brand.
  function pickBrand(value: string | undefined) {
    const item = items.find((i) => i.id === itemId)
    const keep = item && value && (value === NO_BRAND ? !item.brand : item.brand === value)
    setParam('brand', value, { item: keep ? String(itemId) : undefined })
  }

  function pickItem(item: Item | undefined) {
    setParam('item', item ? String(item.id) : undefined, item ? { brand: item.brand ?? NO_BRAND } : {})
  }

  const filterName = [brand, items.find((i) => i.id === itemId)?.model].filter(Boolean).join(' ')
  const page = pathname.replace(/^\/reports\/?/, '').split('/')[0]
  const title = REPORT_PAGES.find(([path]) => path === page)?.[1] ?? 'Overview'
  const context: ReportContext | null = report && { r: report, repId, brand, itemId, byLabel, pickBrand, pickItem, tick }
  // Trends always use the whole history, so the range doesn't apply there.
  const wholeHistory = page === 'trends'

  return (
    <section className="reports">
      <h1>Reports: {title}</h1>
      {page === '' && (
        <p className="lede">
          Starter set of sales KPIs and charts from the deals in the tracker — meant to spark ideas for what's worth
          watching. Hover or tab through a chart for details; every chart has a table view.
        </p>
      )}

      <div className="crud-toolbar filters">
        {!wholeHistory && <label className="inline-label">
          Range
          <select value={preset} onChange={(e) => setParam('range', e.target.value === 'last12' ? undefined : e.target.value)}>
            {PRESETS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>}
        {!wholeHistory && preset === 'custom' && (
          <>
            <label className="inline-label">From
              <input type="month" value={start ?? ''} onChange={(e) => setParam('start', e.target.value)} />
            </label>
            <label className="inline-label">To
              <input type="month" value={end ?? ''} onChange={(e) => setParam('end', e.target.value)} />
            </label>
          </>
        )}
        <label className="inline-label">
          Rep
          <select value={repId ?? ''} onChange={(e) => setParam('rep', e.target.value || undefined)}>
            <option value="">Whole team</option>
            {reps.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </label>
        <label className="inline-label">
          Brand
          <select value={brand ?? ''} onChange={(e) => pickBrand(e.target.value || undefined)}>
            <option value="">All brands</option>
            {brands.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </label>
        <label className="inline-label">
          Model
          <select value={itemId ?? ''} onChange={(e) => pickItem(items.find((i) => i.id === Number(e.target.value)))}>
            <option value="">{brand ? `All ${brand} models` : 'All models'}</option>
            {models.map((i) => <option key={i.id} value={i.id}>{brand ? i.model : itemLabel(i)}</option>)}
          </select>
        </label>
        {report && !wholeHistory && <span className="muted">{long(report.start)} – {long(report.end)}</span>}
      </div>

      {report?.filtered && (
        <p className="banner" role="status">
          Showing only <strong>{filterName}</strong>: each figure counts just those items' share of each deal.
          Quota attainment is hidden while filtered.{' '}
          <button type="button" onClick={() => setParam('brand', undefined, { item: undefined })}>Show everything</button>
        </p>
      )}

      {error && <p className="form-error" role="alert">{error}</p>}
      {!report && !error && <p className="muted">Loading…</p>}

      {context && (
        <div className={loading ? 'reports-body refreshing' : 'reports-body'}>
          <Outlet context={context} />
        </div>
      )}
    </section>
  )
}
