import { AttainmentHeatmap, BarList, ChartCard } from '../../components/charts'
import { compactMoney, money } from '../../lib/format'
import { pct, short, useReport } from './shared'

export default function RepsReportPage() {
  const { r } = useReport()
  const xLabels = r.months.map(short)
  const quotaNote = r.quota_unit === 'usd_thousands' ? 'Quota read as $ thousands (Admin → Settings)'
    : r.quota_unit === 'usd' ? 'Quota read as dollars' : 'Quota read as units sold'
  const repsWithQuota = r.reps.filter((x) => x.attainment != null)
  const byAttainment = [...repsWithQuota].sort((a, b) => b.attainment! - a.attainment!)

  return (
    <div className="viz-grid">
      <ChartCard title="Sales by rep" subtitle="Includes reps left out of the team total (e.g. HOUSE)"
        table={{
          head: ['Rep', 'Sales', 'Deals', 'Avg deal', 'Attainment'], numeric: [false, true, true, true, true],
          rows: r.reps.map((x) => [x.name, money(x.sales_cents), x.deal_count,
            x.avg_deal_cents == null ? '—' : money(x.avg_deal_cents), pct(x.attainment)]),
        }}>
        <BarList label="Sales by rep" rows={r.reps.map((x) => ({
          key: String(x.rep_id), label: x.name, value: x.sales_cents, display: compactMoney(x.sales_cents),
          note: `${x.deal_count} deals · avg ${x.avg_deal_cents == null ? '—' : compactMoney(x.avg_deal_cents)}`,
        }))} />
      </ChartCard>

      {!r.filtered && <ChartCard title="Quota attainment by rep" subtitle={quotaNote}
        table={{
          head: ['Rep', 'Attainment', 'Sales'], numeric: [false, true, true],
          rows: byAttainment.map((x) => [x.name, pct(x.attainment), money(x.sales_cents)]),
        }}>
        <BarList label="Quota attainment by rep" target={{ value: 1, label: '100%' }}
          rows={byAttainment.map((x) => ({
            key: String(x.rep_id), label: x.name, value: x.attainment!, display: pct(x.attainment),
            note: `${compactMoney(x.sales_cents)} sold`,
          }))} />
      </ChartCard>}

      {!r.filtered && <ChartCard wide title="Attainment by rep and month" subtitle="Percent of each month's quota. Spot streaks and slumps."
        table={{
          head: ['Rep', ...xLabels], numeric: [false, ...xLabels.map(() => true)],
          rows: repsWithQuota.map((x) => [x.name, ...x.monthly_attainment.map(pct)]),
        }}>
        <AttainmentHeatmap label="Quota attainment by rep and month" cols={xLabels}
          rows={repsWithQuota.map((x) => ({ key: String(x.rep_id), label: x.name, values: x.monthly_attainment }))} />
      </ChartCard>}
    </div>
  )
}
