// Per-device sign-in token.
const TOKEN_KEY = 'tracker-token'

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
// Old TV links saved a board key; the board is public now, so just forget it.
write('tracker-board-key', null)

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
