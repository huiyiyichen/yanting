/**
 * 预填映射（P1-4）。失败方式：
 * F1 预填字段写进了不属于该工单类型的 localDetail 键。
 * F2 无预填时覆盖表单默认值（是否就医应保持“未知”）。
 * F3 通用“reason”未映射到退货类型的 returnReason。
 */
import { describe, expect, it } from 'vitest'
import { draftToFormValues } from './ticketDraft'

const field = (name: string, value: string) => ({ field: name, value, sourceRef: 'message:S1:m1', quote: value })

describe('draftToFormValues', () => {
  it('F1 maps adverse fields only', () => {
    const values = draftToFormValues({ conversationId: 'S1', workOrderType: 'adverse_reaction', orderId: 'O1',
      fields: [field('symptomDescription', '红肿刺痛'), field('soughtMedicalCare', 'yes'), field('reason', 'x')] })
    expect(values.localDetail).toEqual({ kind: 'adverse_reaction', stoppedUse: 'unknown', soughtMedicalCare: 'yes', symptomDescription: '红肿刺痛' })
    expect(values.orderId).toBe('O1')
  })
  it('F2 keeps defaults without basis', () => {
    const values = draftToFormValues({ conversationId: 'S1', workOrderType: 'adverse_reaction', orderId: null, fields: [] })
    expect(values.localDetail).toMatchObject({ soughtMedicalCare: 'unknown', stoppedUse: 'unknown' })
  })
  it('F3 maps reason to returnReason', () => {
    const values = draftToFormValues({ conversationId: 'S1', workOrderType: 'return_refund', orderId: null, fields: [field('reason', '我要退货')] })
    expect(values.localDetail).toMatchObject({ kind: 'return_refund', returnReason: '我要退货' })
  })
})
