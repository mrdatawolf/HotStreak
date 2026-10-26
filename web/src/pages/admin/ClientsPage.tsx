import { useCallback } from 'react'
import { api, errorMessage, type Client } from '../../api/client'
import CrudTable, { type Field } from '../../components/CrudTable'
import { useLoad } from '../../lib/useLoad'

const FIELDS: Field[] = [
  { key: 'name', label: 'Client', required: true },
  { key: 'location', label: 'Location / branch', placeholder: 'Optional, e.g. Eureka' },
]

export default function ClientsPage() {
  const { data, error, reload } = useLoad(useCallback(() => api.GET('/api/clients', { params: { query: { limit: 1000 } } }), []))

  const body = (v: Record<string, unknown>) => ({ name: String(v.name), location: String(v.location) })

  return (
    <section>
      <h1>Clients</h1>
      <p className="lede">
        Add a separate entry per branch when a client has several locations. Clients with deals can't be deleted.
      </p>
      {error ? <p className="form-error">{errorMessage(error)}</p> : null}
      <CrudTable<Client>
        rows={data ?? []}
        fields={FIELDS}
        addLabel="Add client"
        search={(c, q) => `${c.name} ${c.location ?? ''}`.toLowerCase().includes(q)}
        onCreate={async (v) => {
          const { error } = await api.POST('/api/clients', { body: body(v) })
          if (!error) await reload()
          return error ? errorMessage(error) : null
        }}
        onUpdate={async (c, v) => {
          const { error } = await api.PUT('/api/clients/{client_id}', { params: { path: { client_id: c.id } }, body: body(v) })
          await reload()
          return error ? errorMessage(error) : null
        }}
        onDelete={async (c) => {
          const { error } = await api.DELETE('/api/clients/{client_id}', { params: { path: { client_id: c.id } } })
          await reload()
          return error ? errorMessage(error) : null
        }}
        deleteConfirm={(c) => `Delete ${c.name}${c.location ? ` (${c.location})` : ''}?`}
      />
    </section>
  )
}
