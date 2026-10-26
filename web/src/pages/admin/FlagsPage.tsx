import { useCallback } from 'react'
import { api, errorMessage, type Flag } from '../../api/client'
import CrudTable, { type Field } from '../../components/CrudTable'
import { useLoad } from '../../lib/useLoad'

const FIELDS: Field[] = [
  { key: 'name', label: 'Name', required: true, placeholder: 'e.g. New customer' },
  { key: 'color', label: 'Color', type: 'color' },
]

export default function FlagsPage() {
  const { data, error, reload } = useLoad(useCallback(() => api.GET('/api/flags'), []))

  const body = (v: Record<string, unknown>) => ({ name: String(v.name), color: String(v.color) })

  return (
    <section>
      <h1>Flags</h1>
      <p className="lede">
        Colored markers for deals, like the green highlight on the old sheet. Rename a flag once you know what it means;
        deals keep it.
      </p>
      {error ? <p className="form-error">{errorMessage(error)}</p> : null}
      <CrudTable<Flag>
        rows={data ?? []}
        fields={FIELDS}
        addLabel="Add flag"
        onCreate={async (v) => {
          const { error } = await api.POST('/api/flags', { body: body(v) })
          if (!error) await reload()
          return error ? errorMessage(error) : null
        }}
        onUpdate={async (f, v) => {
          const { error } = await api.PUT('/api/flags/{flag_id}', { params: { path: { flag_id: f.id } }, body: body(v) })
          await reload()
          return error ? errorMessage(error) : null
        }}
        onDelete={async (f) => {
          const { error } = await api.DELETE('/api/flags/{flag_id}', { params: { path: { flag_id: f.id } } })
          await reload()
          return error ? errorMessage(error) : null
        }}
        deleteConfirm={(f) => `Delete "${f.name}"? It will be removed from every deal that has it.`}
      />
    </section>
  )
}
