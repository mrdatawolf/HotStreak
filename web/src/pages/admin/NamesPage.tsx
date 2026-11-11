import { Fragment, useCallback, useMemo, useState, type FormEvent } from 'react'
import { api, errorMessage, type NameKind, type SheetName } from '../../api/client'
import Combobox, { type Option } from '../../components/Combobox'
import { useLoad } from '../../lib/useLoad'

type Show = 'typos' | 'fixed' | 'all'

const SHOW: { value: Show; label: string }[] = [
  { value: 'typos', label: 'Possible typos' },
  { value: 'fixed', label: 'Fixed or checked' },
  { value: 'all', label: 'All names' },
]

const TEXT: Record<NameKind, { title: string; lede: string; count: string; different: string }> = {
  client: {
    title: 'Client names',
    lede: 'Client names as typed on the Google Sheet. When one is a typo of another, fix it here and its deals move to '
      + 'the right client — now and on every later sync. Names that only differ by capitals or punctuation are already '
      + 'grouped. Mark a suggestion as “Not a typo” when two names really are different clients.',
    count: 'Deals',
    different: 'different clients',
  },
  item: {
    title: 'Item names',
    lede: 'Items as typed on the Google Sheet. Merge spellings of the same thing (“Sharp MX-C428F” and “MX-C428F”) so '
      + 'Reports counts them together — now and on every later sync. Spellings that only differ by capitals or '
      + 'punctuation (“XM-3250”, “XM3250”) are already grouped. Suggestions only pair the same model with and without '
      + 'a brand; use Fix… for anything else.',
    count: 'Times sold',
    different: 'different items',
  },
}

function matchesShow(r: SheetName, show: Show) {
  if (show === 'typos') return !r.fix && r.suggestions.length > 0
  if (show === 'fixed') return !!r.fix
  return true
}

export default function NamesPage({ kind }: { kind: NameKind }) {
  const labels = TEXT[kind]
  const { data, error, reload } = useLoad(useCallback(
    () => api.GET('/api/sheet/names/{kind}', { params: { path: { kind } } }), [kind]))
  const [show, setShow] = useState<Show>('typos')
  const [q, setQ] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  const rows = useMemo(() => data ?? [], [data])
  // Names other fixes already point at, so a typo can join an earlier fix.
  const fixTargets = useMemo(() => {
    const counts = new Map<string, number>()
    for (const r of rows) if (r.fix && !r.fix.checked) counts.set(r.fix.target_name, (counts.get(r.fix.target_name) ?? 0) + 1)
    return counts
  }, [rows])
  const allNames = useMemo(
    () => [...new Set(rows.map((r) => r.current_name))].sort((a, b) => a.localeCompare(b)),
    [rows],
  )

  const counts = Object.fromEntries(SHOW.map((s) => [s.value, rows.filter((r) => matchesShow(r, s.value)).length]))
  const needle = q.trim().toLowerCase()
  const shown = rows.filter((r) => matchesShow(r, show)
    && (!needle || `${r.spellings.join(' ')} ${r.current_name}`.toLowerCase().includes(needle)))

  function optionsFor(r: SheetName): Option[] {
    const seen = new Set([r.current_name])
    const out: Option[] = []
    const add = (label: string, detail: string | null) => {
      if (seen.has(label)) return
      seen.add(label)
      out.push({ id: out.length, label, detail })
    }
    r.suggestions.forEach((s) => add(s, 'suggested'))
    ;[...fixTargets].sort((a, b) => b[1] - a[1]).forEach(([name, n]) => add(name, `fix for ${n} spelling${n > 1 ? 's' : ''}`))
    allNames.forEach((name) => add(name, null))
    return out
  }

  async function save(r: SheetName, target: string) {
    const { error } = await api.POST('/api/sheet/name-fixes', { body: { kind, source_name: r.spellings[0], target_name: target } })
    setMessage(error
      ? { kind: 'error', text: errorMessage(error) }
      : { kind: 'ok', text: target === r.spellings[0] ? `Marked “${target}” as checked.` : `“${r.spellings[0]}” now shows as “${target}”.` })
    if (!error) setEditing(null)
    await reload()
  }

  async function undo(r: SheetName) {
    if (!r.fix) return
    const { error } = await api.DELETE('/api/sheet/name-fixes/{fix_id}', { params: { path: { fix_id: r.fix.id } } })
    setMessage(error ? { kind: 'error', text: errorMessage(error) } : { kind: 'ok', text: `Undid the fix for “${r.spellings[0]}”.` })
    await reload()
  }

  async function applyAll() {
    const n = counts.typos
    if (!confirm(`Fix all ${n} suggested names? In each group of similar names, the most-used spelling is kept. `
      + 'You can undo any of them afterwards.')) return
    const { data: done, error } = await api.POST('/api/sheet/names/{kind}/apply-suggestions', { params: { path: { kind } } })
    setMessage(error ? { kind: 'error', text: errorMessage(error) } : { kind: 'ok', text: `Fixed ${done?.length ?? 0} names.` })
    await reload()
  }

  function startEdit(r: SheetName) {
    setEditing(r.key)
    setText(r.fix && !r.fix.checked ? r.fix.target_name : '')
    setMessage(null)
  }

  function submit(e: FormEvent, r: SheetName) {
    e.preventDefault()
    if (text.trim()) void save(r, text.trim())
  }

  return (
    <section>
      <h1>{labels.title}</h1>
      <p className="lede">{labels.lede}</p>

      <div className="crud-toolbar">
        <label className="inline-label">
          Show
          <select value={show} onChange={(e) => setShow(e.target.value as Show)}>
            {SHOW.map((s) => <option key={s.value} value={s.value}>{s.label} ({counts[s.value]})</option>)}
          </select>
        </label>
        <input type="search" placeholder="Search names" aria-label="Search names" value={q} onChange={(e) => setQ(e.target.value)} />
        {counts.typos > 0 && (
          <button className="primary" onClick={applyAll} title={`Use each group's most-used spelling; mark ${labels.different} with “Not a typo” first`}>
            Fix all suggestions
          </button>
        )}
      </div>

      {error ? <p className="form-error">{errorMessage(error)}</p> : null}
      {message && <p className={message.kind === 'ok' ? 'form-ok' : 'form-error'} role="status">{message.text}</p>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>On the sheet</th><th>Shows as</th><th className="num">{labels.count}</th><th>Suggested match</th>
              <th className="actions-col"><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {data && shown.length === 0 && (
              <tr><td colSpan={5} className="muted">{show === 'typos' && !needle ? 'No likely typos left.' : 'No matching names.'}</td></tr>
            )}
            {shown.map((r) => (
              <Fragment key={r.key}>
                <tr>
                  <td data-label="On the sheet">
                    <strong>{r.spellings[0]}</strong>
                    {r.spellings.length > 1 && <span className="muted"> · also {r.spellings.slice(1).join(', ')}</span>}
                  </td>
                  <td data-label="Shows as">{r.current_name === r.spellings[0] ? <span className="muted">same</span> : r.current_name}</td>
                  <td data-label={labels.count} className="num">{r.count}</td>
                  <td data-label="Suggested match">
                    {r.fix
                      ? <span className="muted">{r.fix.checked ? 'Checked, not a typo' : 'Fixed'}
                          {r.fix.created_by_name ? ` by ${r.fix.created_by_name}` : ''}</span>
                      : r.suggestions.length > 0
                        ? <div className="row-actions order-actions">
                            {r.suggestions.map((s) => (
                              <button key={s} title={`Show “${r.spellings[0]}” as “${s}”`} onClick={() => save(r, s)}>Use “{s}”</button>
                            ))}
                          </div>
                        : <span className="muted">—</span>}
                  </td>
                  <td className="actions-col">
                    <div className="row-actions">
                      {r.fix
                        ? <button onClick={() => undo(r)}>Undo</button>
                        : r.suggestions.length > 0 && <button onClick={() => save(r, r.spellings[0])}>Not a typo</button>}
                      <button onClick={() => startEdit(r)}>Fix…</button>
                    </div>
                  </td>
                </tr>
                {editing === r.key && (
                  <tr className="edit-row">
                    <td colSpan={5}>
                      <form className="inline-form" onSubmit={(e) => submit(e, r)}>
                        <span className="field-label">Show “{r.spellings[0]}” as</span>
                        <Combobox
                          label={`Correct name for ${r.spellings[0]}`}
                          value={text}
                          options={optionsFor(r)}
                          onType={setText}
                          onPick={(o) => setText(o.label)}
                          createLabel={(t) => `Use “${t}” as a new name`}
                          onCreate={setText}
                          placeholder="Type to search client names"
                          autoFocus
                        />
                        <button className="primary" disabled={!text.trim()}>Save fix</button>
                        <button type="button" onClick={() => setEditing(null)}>Cancel</button>
                      </form>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
