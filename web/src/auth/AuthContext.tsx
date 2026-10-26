import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, errorMessage, type Me } from '../api/client'
import { getBoardKey, getToken, onUnauthorized, setBoardKey, setToken } from '../lib/session'

type AuthState = {
  me: Me | null
  loading: boolean
  login: (username: string, password: string) => Promise<string | null>
  /** Signs out and reloads to /login. */
  logout: () => Promise<void>
  /** Re-check credentials, e.g. after a board key was saved from the URL. */
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    if (!getToken() && !getBoardKey()) {
      setMe(null)
      setLoading(false)
      return
    }
    const { data } = await api.GET('/api/auth/me')
    setMe(data ?? null)
    setLoading(false)
  }, [])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- state is set after the request resolves
    void refresh()
    return onUnauthorized(() => {
      // The token or board key stopped working; forget it so the user lands on the sign-in page.
      if (getToken()) setToken(null)
      else setBoardKey(null)
      setMe(null)
    })
  }, [refresh])

  const login = useCallback(async (username: string, password: string) => {
    const { data, error } = await api.POST('/api/auth/login', { body: { username, password } })
    if (!data) return errorMessage(error, 'Sign-in failed')
    setToken(data.token)
    setMe(data.user)
    return null
  }, [])

  const logout = useCallback(async () => {
    await api.POST('/api/auth/logout')
    setToken(null)
    // Full reload to a clean sign-in page: drops all in-memory data from this session, and the
    // next person doesn't get sent to the previous user's page via ?next=.
    window.location.assign('/login')
  }, [])

  const value = useMemo(() => ({ me, loading, login, logout, refresh }), [me, loading, login, logout, refresh])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// oxlint-disable-next-line react/only-export-components -- the hook belongs with its provider
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
