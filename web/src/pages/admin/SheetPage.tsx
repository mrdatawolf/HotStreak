import { useCallback, useState } from 'react'
import { Link } from 'react-router'
import { api, errorMessage } from '../../api/client'
import { useLoad } from '../../lib/useLoad'

export default function SheetPage() {
  const { data, error, reload } = useLoad(useCallback(() => api.GET('/api/sheet/sync'), []))
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  async function syncNow() {
    setBusy(true)
    const { error } = await api.POST('/api/sheet/sync')
    setBusy(false)
    setMessage(error ? errorMessage(error) : null)
    await reload()
  }

  const last = data?.last
  const every = data && data.interval_minutes > 0 ? `every ${data.interval_minutes} minutes` : 'when you click Sync now'

  return (
    <section>
      <h1>Google Sheet</h1>
      <p className="lede">
        Deals are still entered on the client's Google Sheet; the app copies it in {every}. Deals from the sheet are
        read-only here (change them on the sheet), and the sheet decides which month is open. Fix typos under{' '}
        <Link to="/admin/client-names">Client names</Link> and <Link to="/admin/item-names">Item names</Link>; fixes are
        kept across syncs.
      </p>
      {(error || message) && <p className="form-error" role="alert">{message ?? errorMessage(error)}</p>}

      {data && !data.configured && (
        <div className="panel settings-block">
          <h2>Set up</h2>
          <ol className="steps">
            <li>In Google Cloud, create a project, enable the <strong>Google Sheets API</strong>, and create a
              service account. Under its <em>Keys</em> tab, add a JSON key and download it.</li>
            <li>Save the key on the server (for example <code>api/secrets/google-service-account.json</code> — keep it
              out of git) and set <code>TRACKER_GOOGLE_CREDENTIALS</code> in <code>.env</code> to its path.</li>
            <li>Share the sheet with the service account's email address as <strong>Viewer</strong>
              {data.service_account ? <> — <code>{data.service_account}</code></> : null}.</li>
            <li>Check <code>TRACKER_GOOGLE_SHEET</code> in <code>.env</code> is the sheet's URL, then restart the API.</li>
          </ol>
        </div>
      )}

      <div className="panel settings-block">
        <h2>Last sync</h2>
        {data?.sheet_url && <p><a href={data.sheet_url} target="_blank" rel="noreferrer">Open the sheet</a></p>}
        {!last && <p className="muted">Not synced yet.</p>}
        {last && (last.ok ? (
          <p className="form-ok" role="status">
            Synced {new Date(last.at).toLocaleString()}
            {last.counts && ` — ${last.counts.months} months, ${last.counts.reps} reps, ${last.counts.clients} clients, ${last.counts.deals} deals.`}
          </p>
        ) : (
          <p className="form-error" role="status">
            Sync failed {new Date(last.at).toLocaleString()}: {last.message}
          </p>
        ))}
        {last?.ok && last.mismatches.length === 0 && <p className="muted">Every rep's total and month total matches the sheet.</p>}
        {last && last.mismatches.length > 0 && (
          <details open>
            <summary>{last.mismatches.length} totals differ from the sheet</summary>
            <ul>{last.mismatches.map((m) => <li key={m}>{m}</li>)}</ul>
          </details>
        )}
        {last && last.warnings.length > 0 && (
          <details>
            <summary>{last.warnings.length} things to check</summary>
            <ul>{last.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
          </details>
        )}
        <div className="row-actions order-actions">
          <button className="primary" disabled={busy || !data?.configured} onClick={syncNow}>
            {busy ? 'Syncing…' : 'Sync now'}
          </button>
        </div>
      </div>
    </section>
  )
}
