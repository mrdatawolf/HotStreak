import { useEffect, useId, useRef, useState } from 'react'
import { NavLink, useLocation } from 'react-router'
import { useAuth } from '../auth/AuthContext'
import FontPicker from './FontPicker'
import ThemeToggle from './ThemeToggle'

const ADMIN_LINKS = [
  ['/admin/sheet', 'Sheet'],
  ['/admin/months', 'Months'],
  ['/admin/users', 'Users'],
  ['/admin/reps', 'Reps'],
  ['/admin/quotas', 'Quotas'],
  ['/admin/items', 'Items'],
  ['/admin/item-names', 'Item names'],
  ['/admin/clients', 'Clients'],
  ['/admin/client-names', 'Client names'],
  ['/admin/flags', 'Flags'],
  ['/admin/settings', 'Settings'],
] as const

/** The header's dropdown: account, display options, and (for admins) the Admin pages. */
export default function SettingsMenu() {
  const { me } = useAuth()
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const panelId = useId()
  const here = pathname.startsWith('/admin') || pathname === '/account'

  // Close after following a link.
  // oxlint-disable-next-line react/set-state-in-effect -- closing on navigation
  useEffect(() => setOpen(false), [pathname])

  useEffect(() => {
    if (!open) return
    function onPointer(e: PointerEvent) {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setOpen(false)
        button.current?.focus()
      }
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="menu" ref={root}>
      <button ref={button} type="button" className={here ? 'menu-button active' : 'menu-button'}
        aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((o) => !o)}>
        Settings <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="menu-panel" id={panelId}>
          {me && !me.is_breakglass && me.role !== 'board' && (
            <div className="menu-group">
              <NavLink to="/account">My account <span className="muted">({me.name})</span></NavLink>
            </div>
          )}
          <div className="menu-group">
            <h3>Display <span className="muted">(this device)</span></h3>
            <ThemeToggle />
            <FontPicker />
          </div>
          {me?.is_admin && (
            <nav className="menu-group" aria-label="Admin">
              <h3>Admin</h3>
              <div className="menu-links">
                {ADMIN_LINKS.map(([to, label]) => <NavLink key={to} to={to}>{label}</NavLink>)}
              </div>
            </nav>
          )}
        </div>
      )}
    </div>
  )
}
