import { NavLink, Outlet, useLocation } from 'react-router'
import { useAuth } from '../auth/AuthContext'
import { REPORT_PAGES } from '../pages/reports/shared'
import SettingsMenu from './SettingsMenu'

export default function AppLayout() {
  const { me, logout } = useAuth()
  // A TV display (board key, no sign-in) only gets the read-only pages.
  const display = me?.role === 'board'
  // Moving between report pages keeps the filters (range, rep, brand, model).
  const { pathname, search } = useLocation()
  const reportSearch = pathname.startsWith('/reports') ? search : ''

  return (
    <div className="app">
      <header className="app-header">
        <nav className="app-nav" aria-label="Main">
          <NavLink to="/board" className="brand">HotStreak</NavLink>
          <NavLink to="/board" end>Board</NavLink>
          {!display && <NavLink to="/deals">Deals</NavLink>}
          <div className="nav-group" role="group" aria-label="Reports">
            <span className="nav-group-label" aria-hidden="true">Reports</span>
            {REPORT_PAGES.map(([path, label]) => (
              <NavLink key={path} to={{ pathname: path ? `/reports/${path}` : '/reports', search: reportSearch }} end>
                {label}
              </NavLink>
            ))}
          </div>
        </nav>
        <div className="app-user">
          {me?.is_breakglass && <span className="badge warn">Break-glass</span>}
          <SettingsMenu />
          {display
            ? <NavLink to="/login">Sign in</NavLink>
            : <button type="button" onClick={logout}>Sign out</button>}
        </div>
      </header>
      {me?.is_breakglass && (
        <p className="banner warn" role="status">
          You're signed in with the break-glass account from <code>.env</code>. Use it for setup and recovery only —
          create a personal admin account under <NavLink to="/admin/users">Users</NavLink> for daily use.
        </p>
      )}
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
