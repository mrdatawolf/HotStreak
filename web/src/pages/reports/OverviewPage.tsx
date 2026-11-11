import { ChartCard, Legend, LineChart, StatTile } from '../../components/charts'
import { compactMoney, money } from '../../lib/format'
import { change, long, pct, short, useReport } from './shared'

export default function OverviewPage() {
  const { r } = useReport()
  const k = r.kpis
  const p = r.prior_kpis
  const vsLabel = `vs prior ${r.months.length} mo`
  const xLabels = r.months.map(short)

  return (
    <>
      <div className="kpi-row">
        <StatTile hero label="Total sales" value={money(k.sales_cents).replace(/\.\d\d$/, '')} delta={change(k.sales_cents, p.sales_cents)}
          deltaLabel={vsLabel} spark={r.monthly.map((m) => m.sales_cents)} />
        <StatTile label="Deals closed" value={k.deal_count.toLocaleString()} delta={change(k.deal_count, p.deal_count)} deltaLabel={vsLabel} />
        <StatTile label="Average deal" value={k.avg_deal_cents == null ? '—' : money(k.avg_deal_cents)}
          delta={change(k.avg_deal_cents, p.avg_deal_cents)} deltaLabel={vsLabel} />
        {!r.filtered && (
          <StatTile label="Quota attainment" value={pct(k.quota_attainment)}
            delta={change(k.quota_attainment, p.quota_attainment)} deltaLabel={vsLabel} note={r.quota_unit === 'usd_thousands' ? 'Quota as $K' : r.quota_unit === 'usd' ? 'Quota as $' : 'Quota as units'} />
        )}
        <StatTile label="Units sold" value={k.units.toLocaleString()} delta={change(k.units, p.units)} deltaLabel={vsLabel} />
        <StatTile label="Active clients" value={k.active_clients.toLocaleString()}
          note={`${k.new_clients} new · ${pct(k.repeat_client_rate)} bought more than once`} />
      </div>

      <div className="viz-grid">
        <ChartCard wide title="Monthly sales" subtitle="Compared with the same months a year earlier"
          legend={<Legend kind="line" series={[
            { key: 'cur', label: 'This period', color: 'var(--series-1)' },
            { key: 'prior', label: 'Year before', color: 'var(--viz-context)' },
          ]} />}
          table={{
            head: ['Month', 'Sales', 'Deals', 'Year before', 'Change', 'Quota attainment'],
            numeric: [false, true, true, true, true, true],
            rows: r.monthly.map((m) => [long(m), money(m.sales_cents), m.deal_count,
              m.prior_year_sales_cents == null ? '—' : money(m.prior_year_sales_cents),
              pct(change(m.sales_cents, m.prior_year_sales_cents)), pct(m.attainment)]),
          }}>
          <LineChart label="Monthly sales, this period vs the year before" xLabels={xLabels} format={money} axisFormat={compactMoney}
            series={[
              { key: 'cur', label: 'This period', color: 'var(--series-1)', values: r.monthly.map((m) => m.sales_cents) },
              { key: 'prior', label: 'Year before', color: 'var(--viz-context)', values: r.monthly.map((m) => m.prior_year_sales_cents) },
            ]} />
        </ChartCard>

        <section className="viz-card ideas">
          <h2>More ideas (need a little more data)</h2>
          <ul>
            <li><strong>Gross margin</strong> by rep and item — add cost to items or deals.</li>
            <li><strong>Lease vs. purchase mix</strong> — a deal type field (or use a flag).</li>
            <li><strong>Pipeline &amp; close rate</strong> — track quotes/opportunities, not just closed deals.</li>
            <li><strong>Commission estimates</strong> — rates per rep or per category.</li>
            <li><strong>Month-to-date pace</strong> — "on pace for $X this month" needs a date on each deal.</li>
            <li><strong>Service contract renewals</strong> — end dates on service lines.</li>
          </ul>
        </section>
      </div>
    </>
  )
}
