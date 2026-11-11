import { useCallback } from 'react'
import { api, errorMessage, type Rep } from '../../api/client'
import CrudTable, { type Field } from '../../components/CrudTable'
import { useLoad } from '../../lib/useLoad'

const FIELDS: Field[] = [
  { key: 'name', label: 'Name', required: true, placeholder: 'e.g. ALEX' },
  { key: 'active', label: 'Active', type: 'checkbox' },
  { key: 'counts_toward_total', label: 'Counts toward monthly total', type: 'checkbox' },
]

export default function RepsPage() {
  const { data, error, reload } = useLoad(useCallback(() => api.GET('/api/reps'), []))

  return (
    <section>
      <h1>Reps</h1>
      <p className="lede">
        Everyone who can appear on the board, including HOUSE. Which reps show on a given month, their order, and their
        quotas are set on the Quotas page. Reps with deals can't be deleted — mark them inactive.
      </p>
      {error ? <p className="form-error">{errorMessage(error)}</p> : null}
      <CrudTable<Rep>
        rows={data ?? []}
        fields={FIELDS}
        addLabel="Add rep"
        rowClass={(r) => (r.active ? undefined : 'inactive')}
        onCreate={async (v) => {
          const { error } = await api.POST('/api/reps', {
            body: { name: String(v.name), active: Boolean(v.active), counts_toward_total: Boolean(v.counts_toward_total) },
          })
          if (!error) await reload()
          return error ? errorMessage(error) : null
        }}
        onUpdate={async (r, v) => {
          const { error } = await api.PATCH('/api/reps/{rep_id}', {
            params: { path: { rep_id: r.id } },
            body: { name: String(v.name), active: Boolean(v.active), counts_toward_total: Boolean(v.counts_toward_total) },
          })
          await reload()
          return error ? errorMessage(error) : null
        }}
        onDelete={async (r) => {
          const { error } = await api.DELETE('/api/reps/{rep_id}', { params: { path: { rep_id: r.id } } })
          await reload()
          return error ? errorMessage(error) : null
        }}
        deleteConfirm={(r) => `Delete ${r.name}? This also removes them from every month's board.`}
      />
    </section>
  )
}
