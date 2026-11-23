import { useCallback } from 'react'
import { api } from '../api/client'
import { useLoad } from './useLoad'

/**
 * True once the Google Sheet has its Deals tab: saves go to the sheet and come back by sync, and admins can
 * change any month (locks only mark which month is current). Null while loading.
 */
export function useSheetMode(): boolean | null {
  const mode = useLoad(useCallback(() => api.GET('/api/deals/mode'), []))
  return mode.data ? mode.data.sheet : null
}
