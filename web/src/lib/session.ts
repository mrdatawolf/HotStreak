// Per-device credentials: a sign-in token, or a read-only board key for TV displays.
const TOKEN_KEY = 'tracker-token'
const BOARD_KEY = 'tracker-board-key'

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string | null) {
  try {
    if (value) localStorage.setItem(key, value)
    else localStorage.removeItem(key)
  } catch {
    // Storage blocked: works until the tab closes.
  }
}

export const getToken = () => read(TOKEN_KEY)
export const setToken = (token: string | null) => write(TOKEN_KEY, token)
export const getBoardKey = () => read(BOARD_KEY)
export const setBoardKey = (key: string | null) => write(BOARD_KEY, key)

type Listener = () => void
const unauthorizedListeners = new Set<Listener>()

export function onUnauthorized(listener: Listener) {
  unauthorizedListeners.add(listener)
  return () => {
    unauthorizedListeners.delete(listener)
  }
}

export function notifyUnauthorized() {
  unauthorizedListeners.forEach((l) => l())
}
