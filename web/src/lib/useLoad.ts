import { useCallback, useEffect, useState } from 'react'

/** Load data on mount (and when `load` changes); `reload` re-fetches after edits. */
export function useLoad<T>(load: () => Promise<{ data?: T; error?: unknown }>) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)

  const reload = useCallback(async () => {
    const res = await load()
    if (res.data !== undefined) {
      setData(res.data)
      setError(null)
    } else {
      setError(res.error ?? 'Failed to load')
    }
  }, [load])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- state is set after the request resolves
    void reload()
  }, [reload])

  return { data, error, reload }
}
