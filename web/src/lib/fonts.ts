// Per-device font choice, kept in localStorage like the theme. Fonts are bundled (no internet needed)
// and only downloaded by the browser when picked.
type Font = { id: string; label: string; family?: string; load?: () => Promise<unknown> }

export const FONTS: Font[] = [
  { id: 'system', label: 'System default' },
  { id: 'inter', label: 'Inter', family: 'Inter Variable', load: () => import('@fontsource-variable/inter') },
  { id: 'roboto', label: 'Roboto', family: 'Roboto Variable', load: () => import('@fontsource-variable/roboto') },
  { id: 'open-sans', label: 'Open Sans', family: 'Open Sans Variable', load: () => import('@fontsource-variable/open-sans') },
  { id: 'source-sans', label: 'Source Sans 3', family: 'Source Sans 3 Variable', load: () => import('@fontsource-variable/source-sans-3') },
  { id: 'nunito', label: 'Nunito', family: 'Nunito Variable', load: () => import('@fontsource-variable/nunito') },
  { id: 'montserrat', label: 'Montserrat', family: 'Montserrat Variable', load: () => import('@fontsource-variable/montserrat') },
  { id: 'lexend', label: 'Lexend', family: 'Lexend Variable', load: () => import('@fontsource-variable/lexend') },
  {
    id: 'atkinson', label: 'Atkinson Hyperlegible (easy to read)', family: 'Atkinson Hyperlegible Next Variable',
    load: () => import('@fontsource-variable/atkinson-hyperlegible-next'),
  },
]

const KEY = 'tracker-font'

export function loadFontChoice(): string {
  try {
    const id = localStorage.getItem(KEY)
    if (id && FONTS.some((f) => f.id === id)) return id
  } catch {
    // Storage blocked; use the default.
  }
  return 'system'
}

export function applyFont(id: string, remember = true) {
  const font = FONTS.find((f) => f.id === id) ?? FONTS[0]
  void font.load?.()
  const root = document.documentElement
  // index.css falls back to the system stack when this isn't set.
  if (font.family) root.style.setProperty('--font-family', `'${font.family}', system-ui, sans-serif`)
  else root.style.removeProperty('--font-family')
  if (!remember) return
  try {
    if (font.id === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, font.id)
  } catch {
    // Still applied for this visit.
  }
}
