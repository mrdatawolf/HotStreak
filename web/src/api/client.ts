import createClient from 'openapi-fetch'
import { getBoardKey, getToken, notifyUnauthorized } from '../lib/session'
import type { components, paths } from './schema'

export const api = createClient<paths>({ baseUrl: import.meta.env.VITE_API_URL ?? '' })

api.use({
  onRequest({ request }) {
    const token = getToken()
    const boardKey = getBoardKey()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    else if (boardKey) request.headers.set('X-Board-Key', boardKey)
    return request
  },
  onResponse({ request, response }) {
    // Session expired, revoked, or the board key was rotated.
    if (response.status === 401 && !request.url.endsWith('/api/auth/login')) notifyUnauthorized()
    return response
  },
})

/** Human-readable message from a FastAPI error body. */
export function errorMessage(error: unknown, fallback = 'Something went wrong'): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d: { loc?: (string | number)[]; msg?: string }) => {
        const field = d.loc?.filter((p) => p !== 'body').join('.')
        return field ? `${field}: ${d.msg}` : d.msg
      })
      .join('; ')
  }
  return fallback
}

type Schemas = components['schemas']
export type Board = Schemas['Board']
export type BoardRep = Schemas['BoardRep']
export type BoardDeal = Schemas['BoardDeal']
export type Period = Schemas['PeriodOut']
export type QuotaUnit = Board['quota_unit']
export type Me = Schemas['Me']
export type User = Schemas['UserOut']
export type Rep = Schemas['RepOut']
export type Client = Schemas['ClientOut']
export type Item = Schemas['ItemOut']
export type Flag = Schemas['FlagOut']
export type PeriodRep = Schemas['PeriodRepOut']
export type AppSettings = Schemas['AppSettings']
export type Deal = Schemas['DealOut']
export type PeriodSummary = Schemas['PeriodSummary']
export type Report = Schemas['Report']
export type Trends = Schemas['Trends']
export type Forecast = Schemas['Forecast']
export type GrowthRow = Schemas['GrowthRow']
export type SheetSyncStatus = Schemas['SheetSyncStatus']
export type SheetName = Schemas['SheetName']
export type NameKind = Schemas['NameFixIn']['kind']
