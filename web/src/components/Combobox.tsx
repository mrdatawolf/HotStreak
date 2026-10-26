import { useId, useState, type KeyboardEvent } from 'react'

export type Option = { id: number; label: string; detail?: string | null }

type Props = {
  label: string
  value: string
  options: Option[]
  /** Called as the user types; the text no longer refers to a picked option. */
  onType: (text: string) => void
  onPick: (option: Option) => void
  /** Offer "+ New …" for text that doesn't match exactly. */
  createLabel?: (text: string) => string
  onCreate?: (text: string) => void
  placeholder?: string
  required?: boolean
  disabled?: boolean
  autoFocus?: boolean
}

const MAX_SHOWN = 40

/** Text input with a filtered suggestion list (ARIA combobox pattern). */
export default function Combobox(props: Props) {
  const { label, value, options, onType, onPick, createLabel, onCreate, placeholder, required, disabled, autoFocus } = props
  const listId = useId()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)

  const q = value.trim().toLowerCase()
  const matches = (q
    ? options.filter((o) => `${o.label} ${o.detail ?? ''}`.toLowerCase().includes(q))
    : options
  ).slice(0, MAX_SHOWN)
  const exact = options.some((o) => o.label.toLowerCase() === q && !o.detail)
  const showCreate = !!(onCreate && createLabel && q && !exact)
  const count = matches.length + (showCreate ? 1 : 0)

  function choose(index: number) {
    if (index < matches.length) onPick(matches[index])
    else if (showCreate) onCreate!(value.trim())
    setOpen(false)
    setActive(-1)
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setOpen(true)
      setActive((a) => Math.min(a + 1, count - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, 0))
    } else if (e.key === 'Enter' && open && active >= 0) {
      e.preventDefault()
      choose(active)
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="combobox">
      <input
        role="combobox"
        aria-label={label}
        aria-expanded={open && count > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
        autoComplete="off"
        value={value}
        placeholder={placeholder}
        required={required}
        disabled={disabled}
        autoFocus={autoFocus}
        onChange={(e) => {
          onType(e.target.value)
          setOpen(true)
          setActive(-1)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      {open && count > 0 && (
        <ul id={listId} role="listbox" className="combobox-list">
          {matches.map((o, i) => (
            <li
              key={o.id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              // mousedown, not click: fires before the input's blur closes the list.
              onMouseDown={(e) => { e.preventDefault(); choose(i) }}
            >
              {o.label}
              {o.detail && <span className="muted"> · {o.detail}</span>}
            </li>
          ))}
          {showCreate && (
            <li id={`${listId}-${matches.length}`} role="option" aria-selected={active === matches.length}
              className="create" onMouseDown={(e) => { e.preventDefault(); choose(matches.length) }}>
              {createLabel!(value.trim())}
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
