/**
 * 证据可见范围文案。
 *
 * 客户可见资料与内部资料的展示口径不同：内部依据只在客服侧出现，
 * 客户接口不返回（工程规范第 12.4 节）。
 */
export function evidenceLabel(visibility: string): string {
  return (
    {
      customer_visible: '客户可见',
      internal: '内部资料',
    }[visibility] ?? visibility
  )
}
