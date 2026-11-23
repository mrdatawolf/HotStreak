import { useCallback, useState } from 'react'
import { api, errorMessage, type QuotaUnit } from '../../api/client'
import { useLoad } from '../../lib/useLoad'

const UNITS: { value: QuotaUnit; label: string }[] = [
  { value: 'usd_thousands', label: 'Thousands of dollars (44 = $44,000)' },
  { value: 'usd', label: 'Dollars' },
  { value: 'units', label: 'Units sold (item quantity)' },
]

export default function SettingsPage() {
  const { data, error, reload } = useLoad(useCallback(() => api.GET('/api/settings'), []))
  const [message, setMessage] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const boardUrl = `${window.location.origin}/board`

  async function act(call: () => Promise<{ error?: unknown }>) {
    const { error } = await call()
    setMessage(error ? errorMessage(error) : null)
    setCopied(false)
    await reload()
  }

  return (
    <section>
      <h1>Settings</h1>
      {(error || message) && <p className="form-error" role="alert">{message ?? errorMessage(error)}</p>}

      <div className="panel settings-block">
        <h2>Quota unit</h2>
        <p className="lede">
          Used for the percent-of-quota bars on the board. The quota number itself is shown as entered.
        </p>
        <select aria-label="Quota unit" value={data?.quota_unit ?? ''} onChange={(e) =>
          act(() => api.PATCH('/api/settings', { body: { quota_unit: e.target.value as QuotaUnit } }))}>
          {UNITS.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
        </select>
      </div>

      <div className="panel settings-block">
        <h2>TV display link</h2>
        <p className="lede">
          The board is public, so the office TV just opens this address — no sign-in or key needed. It shows the board
          only; Reports and everything else need a sign-in.
        </p>
        <div className="copy-row">
          <input readOnly aria-label="TV display link" value={boardUrl} onFocus={(e) => e.target.select()} />
          <button onClick={async () => { await navigator.clipboard.writeText(boardUrl); setCopied(true) }}>
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>
    </section>
  )
}
