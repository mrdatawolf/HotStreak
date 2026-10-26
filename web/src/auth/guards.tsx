import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useAuth } from './AuthContext'

type Need = 'viewer' | 'user' | 'admin'

/** Renders children only for callers with enough access; otherwise sends them to sign in. */
export function RequireAuth({ need, children }: { need: Need; children: ReactNode }) {
  const { me, loading } = useAuth()
  const location = useLocation()

  if (loading) return <main className="board-status">Loading…</main>

  const signedIn = me && me.role !== 'board'
  const allowed = need === 'viewer' ? !!me : need === 'user' ? !!signedIn : !!signedIn && me.is_admin
  if (allowed) return children

  if (signedIn && need === 'admin') {
    return <main className="board-status">Admins only.</main>
  }
  const next = encodeURIComponent(location.pathname + location.search)
  return <Navigate to={`/login?next=${next}`} replace />
}
