/** Parse what someone types in a money field ("$1,234.5") into cents. '' → null; invalid → NaN. */
export function parseMoney(text: string): number | null {
  const cleaned = text.replace(/[$,\s]/g, '')
  if (cleaned === '') return null
  if (!/^\d*(\.\d{0,2})?$/.test(cleaned) || cleaned === '.') return NaN
  return Math.round(Number(cleaned) * 100)
}

/** Cents → editable text without symbols, e.g. 123456 → "1234.56". */
export const centsToInput = (cents: number | null | undefined) => (cents == null ? '' : (cents / 100).toFixed(2))
