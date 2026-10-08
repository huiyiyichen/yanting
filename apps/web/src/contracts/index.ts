/**
 * 契约类型的统一出口。
 *
 * `api.ts` 与 `enums.ts` 都由 `npm run gen:contracts` 从后端 OpenAPI 与枚举导出生成，
 * 不手工维护第二份定义。业务代码从这里导入，避免直接依赖生成文件的内部结构。
 */
export type { components, operations, paths } from './api'
export * from './enums'
