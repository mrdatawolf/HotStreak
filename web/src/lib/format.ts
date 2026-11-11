import type { Period } from '../api/client'

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December']

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

export const money = (cents: number) => usd.format(cents / 100)

export const monthLabel = (p: Pick<Period, 'year' | 'month'>) => `${MONTHS[p.month - 1]} ${p.year}`

// Matches the sheet's tab names, e.g. "09/26".
export const monthShort = (p: Pick<Period, 'year' | 'month'>) =>
  `${String(p.month).padStart(2, '0')}/${String(p.year).slice(-2)}`

// Shown as a plain number, like the sheet, until the client confirms what the unit is.
export const quotaLabel = (quota: number | null) => (quota == null ? '~' : quota.toLocaleString('en-US'))

export const percent = (fraction: number) => `${Math.round(fraction * 100)}%`

/** Short money for chart labels and axes: $950, $12.5K, $1.2M. */
export function compactMoney(cents: number) {
  const d = cents / 100
  const abs = Math.abs(d)
  if (abs >= 1_000_000) return `$${(d / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`
  if (abs >= 1_000) return `$${(d / 1_000).toFixed(abs >= 10_000 ? 0 : 1)}K`
  return `$${Math.round(d)}`
}
