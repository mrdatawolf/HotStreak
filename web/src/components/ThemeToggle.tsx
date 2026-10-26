import { useState } from 'react'
import { applyTheme, loadTheme, type ThemeChoice } from '../lib/theme'

const OPTIONS: { value: ThemeChoice; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

export default function ThemeToggle() {
  const [choice, setChoice] = useState(loadTheme)

  return (
    <div className="theme-toggle" role="radiogroup" aria-label="Theme">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={choice === o.value}
          onClick={() => {
            applyTheme(o.value)
            setChoice(o.value)
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
