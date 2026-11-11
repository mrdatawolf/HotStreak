import { BarList, ChartCard, Columns } from '../../components/charts'
import { compactMoney, money } from '../../lib/format'
import { pct, useReport } from './shared'

export default function ClientsReportPage() {
  const { r } = useReport()
  const k = r.kpis

  return (
    <>
      <p className="muted">
        {k.active_clients.toLocaleString()} clients bought in this range · {k.new_clients} new ·{' '}
        {pct(k.repeat_client_rate)} bought more than once
      </p>
      <div className="viz-grid">
        <ChartCard title="Top clients"
          subtitle={r.top_clients_share == null ? 'By sales' : `By sales · top ${r.top_clients.length} = ${pct(r.top_clients_share)} of all sales`}
          table={{
            head: ['Client', 'Location', 'Sales', 'Deals'], numeric: [false, false, true, true],
            rows: r.top_clients.map((x) => [x.label, x.detail ?? '', money(x.sales_cents), x.count]),
          }}>
          <BarList label="Top clients by sales" rows={r.top_clients.map((x) => ({
            key: `${x.label}|${x.detail}`, label: x.detail ? `${x.label} (${x.detail})` : x.label, value: x.sales_cents,
            display: compactMoney(x.sales_cents), note: `${x.count} deals`,
          }))} />
        </ChartCard>

        <ChartCard title="Deal size" subtitle="Number of deals by total"
          table={{
            head: ['Deal size', 'Deals', 'Sales'], numeric: [false, true, true],
            rows: r.deal_sizes.map((b) => [b.label, b.deal_count, money(b.sales_cents)]),
          }}>
          <Columns label="Number of deals by size" rows={r.deal_sizes.map((b) => ({
            key: b.label, label: b.label, value: b.deal_count, display: String(b.deal_count),
            note: `${compactMoney(b.sales_cents)} in sales`,
          }))} />
        </ChartCard>
      </div>
    </>
  )
}
