import { useOutletContext } from 'react-router'
import type { Item, Report } from '../../api/client'

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export const short = (k: { year: number; month: number }) => `${MON[k.month - 1]} ’${String(k.year).slice(-2)}`
export const long = (k: { year: number; month: number }) => `${MON[k.month - 1]} ${k.year}`
export const ym = (year: number, month: number) => `${year}-${String(month).padStart(2, '0')}`
export const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`)

export function change(cur: number | null | undefined, prior: number | null | undefined) {
  if (cur == null || prior == null || prior === 0) return null
  return (cur - prior) / prior
}

// Must match the API's label for items without a brand.
export const NO_BRAND = '(no brand)'

export const itemLabel = (i: Item) => (i.brand ? `${i.brand} ${i.model}` : i.model)

/** The report pages, in header order. Paths are under /reports. */
export const REPORT_PAGES = [
  ['', 'Overview'],
  ['reps', 'Reps'],
  ['products', 'Products'],
  ['clients', 'Clients'],
  ['trends', 'Trends'],
] as const

/** What ReportsLayout hands each report page. */
export interface ReportContext {
  r: Report
  repId: number | undefined
  brand: string | undefined
  itemId: number | undefined
  byLabel: Map<string, Item>
  pickBrand: (value: string | undefined) => void
  pickItem: (item: Item | undefined) => void
  // Bumped every few minutes; pages that load their own data reload on it.
  tick: number
}

export const useReport = () => useOutletContext<ReportContext>()
