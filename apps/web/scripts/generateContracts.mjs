/**
 * 契约生成：从后端取 OpenAPI 与其枚举导出，产出前端类型与共享契约产物。
 *
 * 目的（工程规范第 4.1 节）：前端 TypeScript 类型由 OpenAPI/JSON Schema 生成，
 * 不手工复制；枚举定义唯一来源在后端，不手工维护第二份。
 *
 * 用法：
 *   node scripts/generateContracts.mjs                # 从 http://127.0.0.1:8000 拉取
 *   node scripts/generateContracts.mjs --from-file <path>
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import openapiTS, { astToString } from 'openapi-typescript'

const here = dirname(fileURLToPath(import.meta.url))
const webRoot = resolve(here, '..')
const repoRoot = resolve(webRoot, '../..')

const apiBase = process.env.ANKER_AGENT_API_BASE ?? 'http://127.0.0.1:8000'
const args = process.argv.slice(2)
const fromFileIndex = args.indexOf('--from-file')
const fromFile = fromFileIndex >= 0 ? args[fromFileIndex + 1] : null

const contractsDir = resolve(repoRoot, 'packages/contracts')
const generatedDir = resolve(contractsDir, 'generated')
const enumsDir = resolve(contractsDir, 'enums')
const apiTypesPath = resolve(webRoot, 'src/contracts/api.ts')

mkdirSync(generatedDir, { recursive: true })
mkdirSync(enumsDir, { recursive: true })
mkdirSync(dirname(apiTypesPath), { recursive: true })

async function loadSpec() {
  if (fromFile) {
    const { readFileSync } = await import('node:fs')
    return JSON.parse(readFileSync(fromFile, 'utf8'))
  }
  const response = await fetch(`${apiBase}/openapi.json`)
  if (!response.ok) {
    throw new Error(
      `拉取 OpenAPI 失败：HTTP ${response.status}。请先启动后端，或使用 --from-file。`,
    )
  }
  return await response.json()
}

async function loadEnums() {
  if (fromFile) {
    const { readFileSync } = await import('node:fs')
    return JSON.parse(readFileSync(fromFile.replace(/\.json$/, '.enums.json'), 'utf8'))
  }
  const response = await fetch(`${apiBase}/api/contracts/enums`)
  if (!response.ok) {
    throw new Error(`拉取枚举失败：HTTP ${response.status}`)
  }
  return await response.json()
}

/** camelCase -> SCREAMING_SNAKE_CASE，用于生成 VALUES 常量名。 */
function toScreamingSnake(name) {
  return name.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toUpperCase()
}

function enumsToTypeScript(enums) {
  const lines = [
    '/**',
    ' * 本文件由 scripts/generateContracts.mjs 从后端枚举导出自动生成，请勿手工修改。',
    ' * 机器值唯一来源：services/api/app/domain/enums.py',
    ' */',
    '',
  ]
  for (const [name, mapping] of Object.entries(enums)) {
    const typeName = name.charAt(0).toUpperCase() + name.slice(1)
    const valuesName = `${toScreamingSnake(name)}_VALUES`
    lines.push(`export const ${valuesName} = [`)
    for (const value of Object.keys(mapping)) {
      lines.push(`  '${value}',`)
    }
    lines.push('] as const')
    lines.push('')
    lines.push(`export type ${typeName} = (typeof ${valuesName})[number]`)
    lines.push('')
    lines.push(`export const ${name}Labels: Record<${typeName}, string> = ${JSON.stringify(mapping, null, 2)}`)
    lines.push('')
  }
  return lines.join('\n')
}

const spec = await loadSpec()
const enums = await loadEnums()

writeFileSync(resolve(generatedDir, 'openapi.json'), JSON.stringify(spec, null, 2), 'utf8')
writeFileSync(resolve(enumsDir, 'enums.json'), JSON.stringify(enums, null, 2), 'utf8')

// 使用 openapi-typescript 的编程式 API，避免通过子进程调用 npx：
// 子进程管道在受限环境下不可用，且编程式 API 少一层退出码与路径问题。
const ast = await openapiTS(spec)
const generated = astToString(ast)

const header = `/**
 * 本文件由 scripts/generateContracts.mjs 自动生成，请勿手工修改。
 * 来源：${fromFile ?? `${apiBase}/openapi.json`}
 * 字段命名为 camelCase，与后端 Pydantic 序列化别名一致。
 */

`
writeFileSync(apiTypesPath, header + generated, 'utf8')
writeFileSync(resolve(webRoot, 'src/contracts/enums.ts'), enumsToTypeScript(enums), 'utf8')

const enumCount = Object.keys(enums).length
const valueCount = Object.values(enums).reduce((sum, item) => sum + Object.keys(item).length, 0)
console.log(
  `契约已生成：${enumCount} 个枚举 / ${valueCount} 个机器值；类型写入 src/contracts/api.ts`,
)
