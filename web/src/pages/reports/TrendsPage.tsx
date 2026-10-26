import { useEffect, useState } from 'react'
import { api, errorMessage, type Forecast, type GrowthRow, type Trends } from '../../api/client'
import { BarList, ChartCard, Columns, Legend, LineChart, StatTile } from '../../components/charts'
import { compactMoney, money } from '../../lib/format'
import { change, long, pct, short, useReport } from './shared'

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
// Months shown in the moving-average chart.
const RECENT_MONTHS = 24

const whole = (cents: number) => money(cents).replace(/\.\d\d$/, '')
const signed = (v: number | null | undefined) => (v == null ? '—' : `${v > 0 ? '+' : ''}${Math.round(v * 100)}%`)

/** Whole-history trends and quarter/year forecasts; follows the rep/brand/model filters but not the range. */
export default function TrendsPage() {
  const { repId, brand, itemId, tick } = useReport()
  const [t, setT] = useState<Trends | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.GET('/api/reports/trends', { params: { query: { rep_id: repId, brand, item_id: itemId } } }).then(({ data, error }) => {
      if (cancelled) return
      if (data) setT(data)
      setError(data ? null : errorMessage(error))
    })
    return () => { cancelled = true }
  }, [repId, brand, itemId, tick])

  if (error) return <p className="form-error" role="alert">{error}</p>
  if (!t) return <p className="muted">Loading…</p>

  const finished = t.months.filter((m) => m.complete)
  const rolling = finished.filter((m) => m.ttm_cents != null)
  const recent = finished.slice(-RECENT_MONTHS)
  const quarters = t.quarters.filter((q) => q.complete)
  const qLabel = (q: { year: number; quarter: number }) => `Q${q.quarter} ’${String(q.year).slice(-2)}`
  const a = t.averages
  const ytdSpan = t.ytd ? `Jan–${MON[t.ytd.through.month - 1]}` : ''

  return (
    <>
      <p className="lede">
        Uses every month in the tracker{t.last_complete && <> through {long(t.last_complete)}</>}. {long(t.current)} is
        still open, so it's left out of trends and averages. Single months swing too much to forecast, so forecasts are
        for the quarter and year; each range is how far the same method has missed on past data.
      </p>

      {t.forecasts.length > 0 ? (
        <div className="forecast-row">
          {t.forecasts.map((f) => <ForecastCard key={f.label} f={f} openMonth={long(t.current)} />)}
        </div>
      ) : (
        <p className="muted">Forecasts need at least 12 finished months.</p>
      )}

      <div className="kpi-row plain">
        {t.ytd && (
          <StatTile label={`Year to date (${ytdSpan})`} value={whole(t.ytd.sales_cents)}
            delta={change(t.ytd.sales_cents, t.ytd.prior_sales_cents)} deltaLabel={`vs ${ytdSpan} ${t.ytd.through.year - 1}`}
            note={`${t.ytd.deal_count} deals${t.ytd.prior_deal_count == null ? '' : ` (${t.ytd.prior_deal_count} last year)`}`} />
        )}
        <StatTile label="Monthly average, last 12 months" value={a.monthly_12_cents == null ? '—' : whole(a.monthly_12_cents)}
          note={`Last 6: ${a.monthly_6_cents == null ? '—' : compactMoney(a.monthly_6_cents)} · last 3: ${a.monthly_3_cents == null ? '—' : compactMoney(a.monthly_3_cents)}`} />
        <StatTile label="Deals per month, last 12" value={a.deals_per_month_12 == null ? '—' : a.deals_per_month_12.toFixed(1)} />
        <StatTile label="Average deal, last 12 months" value={a.avg_deal_12_cents == null ? '—' : money(a.avg_deal_12_cents)} />
      </div>

      <div className="viz-grid">
        <ChartCard wide title="Rolling 12-month sales"
          subtitle="Each point is the total of the 12 months ending there, which evens out the monthly swings. The clearest trend line."
          table={{
            head: ['12 months ending', 'Total', 'Change vs a year earlier'], numeric: [false, true, true],
            rows: rolling.map((m, i) => [long(m), money(m.ttm_cents!), signed(i >= 12 ? change(m.ttm_cents, rolling[i - 12].ttm_cents) : null)]),
          }}>
          <LineChart label="Rolling 12-month sales" xLabels={rolling.map(short)} format={money} axisFormat={compactMoney}
            series={[{ key: 'ttm', label: '12-month total', color: 'var(--series-1)', values: rolling.map((m) => m.ttm_cents) }]} />
        </ChartCard>

        <ChartCard wide title="Monthly sales and 3-month average"
          subtitle={`Last ${recent.length} finished months. Single months are noisy; the average shows the direction.`}
          legend={<Legend kind="line" series={[
            { key: 'avg', label: '3-month average', color: 'var(--series-1)' },
            { key: 'month', label: 'Month', color: 'var(--viz-context)' },
          ]} />}
          table={{
            head: ['Month', 'Sales', 'Deals', '3-month average', 'vs month before', 'vs a year earlier'],
            numeric: [false, true, true, true, true, true],
            rows: recent.map((m) => {
              const i = finished.indexOf(m)
              const prev = finished[i - 1]
              const yearAgo = finished.find((x) => x.year === m.year - 1 && x.month === m.month)
              return [long(m), money(m.sales_cents), m.deal_count, m.avg3_cents == null ? '—' : money(m.avg3_cents),
                signed(change(m.sales_cents, prev?.sales_cents)), signed(change(m.sales_cents, yearAgo?.sales_cents))]
            }),
          }}>
          <LineChart label="Monthly sales with 3-month average" xLabels={recent.map(short)} format={money} axisFormat={compactMoney}
            series={[
              { key: 'month', label: 'Month', color: 'var(--viz-context)', values: recent.map((m) => m.sales_cents) },
              { key: 'avg', label: '3-month average', color: 'var(--series-1)', values: recent.map((m) => m.avg3_cents) },
            ]} />
        </ChartCard>

        <ChartCard wide title="Quarter by quarter" subtitle="Each finished quarter against the same quarter a year earlier"
          legend={<Legend kind="line" series={[
            { key: 'q', label: 'Quarter', color: 'var(--series-1)' },
            { key: 'ly', label: 'Same quarter last year', color: 'var(--viz-context)' },
          ]} />}
          table={{
            head: ['Quarter', 'Sales', 'Deals', 'vs quarter before', 'Same quarter last year', 'vs last year'],
            numeric: [false, true, true, true, true, true],
            rows: t.quarters.map((q) => [q.complete ? qLabel(q) : `${qLabel(q)} (so far)`, money(q.sales_cents), q.deal_count,
              q.complete ? signed(change(q.sales_cents, q.prior_quarter_sales_cents)) : '—',
              q.prior_year_sales_cents == null ? '—' : money(q.prior_year_sales_cents),
              q.complete ? signed(change(q.sales_cents, q.prior_year_sales_cents)) : '—']),
          }}>
          <LineChart label="Quarterly sales vs the same quarter last year" xLabels={quarters.map(qLabel)} format={money} axisFormat={compactMoney}
            series={[
              { key: 'q', label: 'Quarter', color: 'var(--series-1)', values: quarters.map((q) => q.sales_cents) },
              { key: 'ly', label: 'Same quarter last year', color: 'var(--viz-context)', values: quarters.map((q) => q.prior_year_sales_cents) },
            ]} />
        </ChartCard>

        <ChartCard title="Year by year" subtitle="Average sales per month, so partial years compare fairly (finished months only)"
          table={{
            head: ['Year', 'Months', 'Sales', 'Deals', 'Monthly average'], numeric: [false, true, true, true, true],
            rows: t.years.map((y) => [y.year, y.months, money(y.sales_cents), y.deal_count, money(y.sales_cents / y.months)]),
          }}>
          <Columns label="Average monthly sales by year" rows={t.years.map((y) => ({
            key: String(y.year), label: y.months < 12 ? `${y.year} (${y.months} mo)` : String(y.year),
            value: y.sales_cents / y.months, display: compactMoney(y.sales_cents / y.months),
            note: `${compactMoney(y.sales_cents)} in ${y.months} months`,
          }))} />
        </ChartCard>

        <ChartCard title="Average by calendar month"
          subtitle="A weak pattern from only a few years of each month; a rough guide to busier and quieter months"
          table={{
            head: ['Month', 'Average sales', 'Years'], numeric: [false, true, true],
            rows: t.calendar.map((c) => [MON[c.month - 1], money(c.avg_sales_cents), c.years]),
          }}>
          <Columns label="Average sales by calendar month" rows={t.calendar.map((c) => ({
            key: String(c.month), label: MON[c.month - 1], value: c.avg_sales_cents, display: compactMoney(c.avg_sales_cents),
            note: `average of ${c.years} years`,
          }))} />
        </ChartCard>

        {t.rep_growth.length > 0 && <GrowthCard title="Growth by rep" rows={t.rep_growth}
          subtitle="Last 12 finished months vs the 12 before. Includes reps left out of the team total (e.g. HOUSE)" />}
        {t.brand_growth.length > 0 && !brand && <GrowthCard title="Growth by brand" rows={t.brand_growth}
          subtitle="Last 12 finished months vs the 12 before. Deal totals are split across their lines" />}
      </div>
    </>
  )
}

function ForecastCard({ f, openMonth }: { f: Forecast; openMonth: string }) {
  return (
    <section className="stat forecast">
      <div className="stat-label">{f.label}</div>
      <div className="stat-value">{whole(f.estimate_cents)}</div>
      {f.low_cents != null && f.high_cents != null && (
        <div className="forecast-range">
          Likely {compactMoney(f.low_cents)} – {compactMoney(f.high_cents)}
          <span className="muted"> (past misses averaged ±{pct(f.typical_miss)})</span>
        </div>
      )}
      <dl className="forecast-facts">
        <dt>Basis</dt>
        <dd>{f.months_actual > 0 ? `${compactMoney(f.actual_cents)} from ${f.months_actual} finished months, plus ` : ''}
          {f.months_total - f.months_actual} months at the 12-month average
          {f.includes_open_month && ` (${openMonth} uses its sales so far if higher)`}</dd>
        {f.last_year_cents != null && (
          <><dt>Last year</dt><dd>{compactMoney(f.last_year_cents)} ({signed(change(f.estimate_cents, f.last_year_cents))})</dd></>
        )}
        {f.quota_cents != null && (
          <><dt>Quota</dt><dd>{compactMoney(f.quota_cents)} ({pct(f.estimate_cents / f.quota_cents)} of quota)</dd></>
        )}
      </dl>
    </section>
  )
}

function GrowthCard({ title, subtitle, rows }: { title: string; subtitle: string; rows: GrowthRow[] }) {
  return (
    <ChartCard title={title} subtitle={subtitle}
      table={{
        head: ['Name', 'Last 12 months', '12 months before', 'Change'], numeric: [false, true, true, true],
        rows: rows.map((r) => [r.label, money(r.sales_cents), money(r.prior_sales_cents), r.change == null ? 'new' : signed(r.change)]),
      }}>
      <BarList label={title} rows={rows.filter((r) => r.sales_cents > 0).slice(0, 10).map((r) => ({
        key: r.label, label: r.label, value: r.sales_cents, display: compactMoney(r.sales_cents),
        note: r.change == null ? 'new this year' : `${signed(r.change)} vs ${compactMoney(r.prior_sales_cents)}`,
      }))} />
    </ChartCard>
  )
}
