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

  const boardUrl = data?.board_key ? `${window.location.origin}/board?key=${encodeURIComponent(data.board_key)}` : null

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
          Open this link once on the office TV. It remembers the key and shows the board without anyone signing in.
          The key only opens the board — nothing else. Making a new link disconnects every display using the old one.
        </p>
        {boardUrl ? (
          <>
            <div className="copy-row">
              <input readOnly aria-label="TV display link" value={boardUrl} onFocus={(e) => e.target.select()} />
              <button onClick={async () => { await navigator.clipboard.writeText(boardUrl); setCopied(true) }}>
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <div className="row-actions">
              <button onClick={() => confirm('Make a new link? Displays using the current one will stop working.')
                && act(() => api.POST('/api/settings/board-key'))}>New link</button>
              <button className="danger" onClick={() => confirm('Turn off the TV link? Displays using it will stop working.')
                && act(() => api.DELETE('/api/settings/board-key'))}>Turn off</button>
            </div>
          </>
        ) : (
          <button className="primary" onClick={() => act(() => api.POST('/api/settings/board-key'))}>Create TV link</button>
        )}
      </div>
    </section>
  )
}
