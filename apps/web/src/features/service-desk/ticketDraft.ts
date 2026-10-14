import type { TicketCreateRequest, TicketDetail, TicketDraftView, TicketView } from '../../api/client'
import { newTicketDetail } from './TicketDetailFields'

const FIELD_KEYS: Record<TicketView['workOrderType'], Record<string, string>> = {
  adverse_reaction: { symptomDescription: 'symptomDescription', affectedArea: 'affectedArea', onsetInterval: 'onsetInterval',
    productBatchNo: 'productBatchNo', stoppedUse: 'stoppedUse', soughtMedicalCare: 'soughtMedicalCare' },
  reship_exchange: { reason: 'reason' },
  offline_payment: { reason: 'reason' },
  logistics: { reason: 'reason' },
  return_refund: { reason: 'returnReason' },
}

/** 把规则预填结果映射为建单表单初值；无依据的字段保持类型默认值。 */
export function draftToFormValues(draft: TicketDraftView): Partial<TicketCreateRequest> {
  const kind = draft.workOrderType as TicketView['workOrderType'] | null
  if (!kind) return { conversationId: draft.conversationId, orderId: draft.orderId ?? undefined }
  const detail: Record<string, unknown> = { ...newTicketDetail(kind) }
  for (const item of draft.fields) {
    const key = FIELD_KEYS[kind][item.field]
    if (key) detail[key] = item.value
  }
  return { conversationId: draft.conversationId, orderId: draft.orderId ?? undefined, workOrderType: kind,
    localDetail: detail as TicketDetail }
}
