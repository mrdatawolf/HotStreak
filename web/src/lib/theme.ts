// Per-device theme choice, kept in localStorage. index.html applies it before first paint.
export type ThemeChoice = 'system' | 'light' | 'dark'

const KEY = 'tracker-theme'

export function loadTheme(): ThemeChoice {
  try {
    const value = localStorage.getItem(KEY)
    if (value === 'light' || value === 'dark') return value
  } catch {
    // Storage can be blocked (private mode, kiosk settings); fall back to system.
  }
  return 'system'
}

export function applyTheme(choice: ThemeChoice) {
  const root = document.documentElement
  if (choice === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', choice)
  try {
    if (choice === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, choice)
  } catch {
    // Still applied for this visit, just not remembered.
  }
}
