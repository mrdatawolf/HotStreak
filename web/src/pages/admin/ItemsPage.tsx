import { useCallback } from 'react'
import { api, errorMessage, type Item } from '../../api/client'
import CrudTable, { type Field } from '../../components/CrudTable'
import { useLoad } from '../../lib/useLoad'

const CATEGORIES = [
  { value: 'mfp', label: 'MFP / copier' },
  { value: 'printer', label: 'Printer' },
  { value: 'software', label: 'Software' },
  { value: 'accessory', label: 'Accessory' },
  { value: 'service', label: 'Service' },
  { value: 'other', label: 'Other' },
] as const

const FIELDS: Field[] = [
  { key: 'brand', label: 'Brand', placeholder: 'e.g. Lexmark' },
  { key: 'model', label: 'Model', required: true, placeholder: 'e.g. XC2335' },
  { key: 'category', label: 'Category', type: 'select', options: CATEGORIES },
]

export default function ItemsPage() {
  const { data, error, reload } = useLoad(useCallback(() => api.GET('/api/items', { params: { query: { limit: 1000 } } }), []))

  const body = (v: Record<string, unknown>) => ({
    brand: String(v.brand), model: String(v.model), category: v.category as Item['category'],
  })

  return (
    <section>
      <h1>Items</h1>
      <p className="lede">The catalog of things that get sold. Items already on deals can't be deleted.</p>
      {error ? <p className="form-error">{errorMessage(error)}</p> : null}
      <CrudTable<Item>
        rows={data ?? []}
        fields={FIELDS}
        addLabel="Add item"
        search={(i, q) => `${i.brand ?? ''} ${i.model} ${i.category}`.toLowerCase().includes(q)}
        onCreate={async (v) => {
          const { error } = await api.POST('/api/items', { body: body(v) })
          if (!error) await reload()
          return error ? errorMessage(error) : null
        }}
        onUpdate={async (i, v) => {
          const { error } = await api.PUT('/api/items/{item_id}', { params: { path: { item_id: i.id } }, body: body(v) })
          await reload()
          return error ? errorMessage(error) : null
        }}
        onDelete={async (i) => {
          const { error } = await api.DELETE('/api/items/{item_id}', { params: { path: { item_id: i.id } } })
          await reload()
          return error ? errorMessage(error) : null
        }}
        deleteConfirm={(i) => `Delete ${[i.brand, i.model].filter(Boolean).join(' ')}?`}
      />
    </section>
  )
}
