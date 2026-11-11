import { BarList, ChartCard, Legend, StackedColumns } from '../../components/charts'
import { compactMoney, money } from '../../lib/format'
import { long, short, useReport } from './shared'

// Color follows the category, never its rank, so filters never repaint a category.
const CATEGORY: Record<string, { label: string; color: string }> = {
  mfp: { label: 'MFP / copier', color: 'var(--series-1)' },
  printer: { label: 'Printer', color: 'var(--series-2)' },
  software: { label: 'Software', color: 'var(--series-3)' },
  accessory: { label: 'Accessory', color: 'var(--series-4)' },
  service: { label: 'Service', color: 'var(--series-5)' },
  other: { label: 'Other / free text', color: 'var(--series-6)' },
}

const MIX_REST = 'Everything else'
const MIX_COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)']

// Colors follow position in the mix; "Everything else" is always the muted context color.
function mixColor(series: string, index: number) {
  return series === MIX_REST ? 'var(--viz-context)' : MIX_COLORS[index % MIX_COLORS.length]
}

export default function ProductsPage() {
  const { r, brand, itemId, byLabel, pickBrand, pickItem } = useReport()
  const xLabels = r.months.map(short)

  return (
    <div className="viz-grid">
      <ChartCard wide title={r.mix_by === 'brand' ? 'Sales by brand, month by month' : `${brand} sales by model, month by month`}
        subtitle={`Top ${Math.min(r.mix_series.length, MIX_COLORS.length)} ${r.mix_by === 'brand' ? 'brands' : 'models'}`
          + (r.mix_series.includes(MIX_REST) ? '; the rest grouped' : '') + '. Deal totals are split across their lines.'}
        legend={<Legend series={r.mix_series.map((s, i) => ({ key: s, label: s, color: mixColor(s, i) }))} />}
        table={{
          head: ['Month', ...r.mix_series], numeric: [false, ...r.mix_series.map(() => true)],
          rows: r.mix_monthly.map((m) => [long(m), ...r.mix_series.map((s) => money(m.sales_cents[s] ?? 0))]),
        }}>
        <StackedColumns label={`Sales by ${r.mix_by} and month`} xLabels={xLabels} format={money} axisFormat={compactMoney}
          series={r.mix_series.map((s, i) => ({
            key: s, label: s, color: mixColor(s, i), values: r.mix_monthly.map((m) => m.sales_cents[s] ?? 0),
          }))} />
      </ChartCard>

      {!brand && (
        <ChartCard title="Sales by brand" subtitle="Click a brand to see just its numbers"
          table={{
            head: ['Brand', 'Sales', 'Units'], numeric: [false, true, true],
            rows: r.brands.map((x) => [x.label, money(x.sales_cents), x.count]),
          }}>
          <BarList label="Sales by brand" onSelect={(row) => pickBrand(row.key)}
            rows={r.brands.slice(0, 10).map((x) => ({
              key: x.label, label: x.label, value: x.sales_cents, display: compactMoney(x.sales_cents), note: `${x.count} units`,
            }))} />
        </ChartCard>
      )}

      <ChartCard title={brand ? `${brand} models` : 'Sales by model'}
        subtitle={`Top ${Math.min(10, r.items.length)} of ${r.items.length} by sales (table view lists all)${itemId ? '' : ' · click one to see just it'}`}
        table={{
          head: ['Brand', 'Model', 'Category', 'Sales', 'Units'], numeric: [false, false, false, true, true],
          rows: r.items.map((x) => {
            const item = byLabel.get(x.label)
            return [item?.brand ?? '', item?.model ?? x.label, CATEGORY[x.detail ?? 'other']?.label ?? x.detail ?? '',
              money(x.sales_cents), x.count]
          }),
        }}>
        <BarList label="Sales by model" onSelect={itemId ? undefined : (row) => pickItem(byLabel.get(row.key))}
          rows={r.items.slice(0, 10).map((x) => ({
            key: x.label, label: brand ? byLabel.get(x.label)?.model ?? x.label : x.label,
            detail: CATEGORY[x.detail ?? 'other']?.label, value: x.sales_cents,
            display: compactMoney(x.sales_cents), note: `${x.count} units`,
          }))} />
      </ChartCard>

      <ChartCard wide title="Sales by category" subtitle="Product mix each month. Deal totals are split across their lines."
        legend={<Legend series={r.categories.map((c) => ({ key: c, ...CATEGORY[c] }))} />}
        table={{
          head: ['Month', ...r.categories.map((c) => CATEGORY[c].label)], numeric: [false, ...r.categories.map(() => true)],
          rows: r.category_monthly.map((m) => [long(m), ...r.categories.map((c) => money(m.sales_cents[c] ?? 0))]),
        }}>
        <StackedColumns label="Sales by category and month" xLabels={xLabels} format={money} axisFormat={compactMoney}
          series={r.categories.map((c) => ({
            key: c, ...CATEGORY[c], values: r.category_monthly.map((m) => m.sales_cents[c] ?? 0),
          }))} />
      </ChartCard>
    </div>
  )
}
