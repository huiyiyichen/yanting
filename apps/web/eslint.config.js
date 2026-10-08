import js from '@eslint/js'
import tseslint from 'typescript-eslint'

/**
 * ESLint 扁平配置（ESLint 9 只认这个格式）。
 *
 * 为什么补：`package.json` 里一直有 `npm run lint`，但仓库里没有 `eslint.config.js`，
 * ESLint 9 会直接报「找不到配置文件」并以退出码 2 结束——这条 lint 入口实际上
 * 从未可用（S0 要求「建立真实可用的 lint 命令」，这条当时不成立，已登记为缺陷第 50 项）。
 *
 * 取舍：
 * - **不新增依赖**。`globals` 包只是被别的包间接装进来的（不是直接依赖），
 *   依赖它的 hoist 位置很脆；Node 侧需要的全局量很少，直接列出来更稳。
 * - 不做类型感知检查（需要额外 project service 配置），避免把 lint 变成第二遍 `tsc`。
 * - React Hooks 专用规则需要 `eslint-plugin-react-hooks`，本期不为 lint 增依赖；
 *   Hooks 用法错误由 `tsc -b` 与组件测试兜住。
 * - TS 文件里 `no-undef` 由 typescript-eslint 的 eslint-recommended 关闭：
 *   浏览器/Node 全局量本来由 TypeScript 自己校验，重复检查只会互相打架。
 */
const NODE_GLOBALS = {
  process: 'readonly',
  console: 'readonly',
  Buffer: 'readonly',
  fetch: 'readonly',
  URL: 'readonly',
  setTimeout: 'readonly',
  clearTimeout: 'readonly',
}

export default tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**', 'playwright-report/**', 'test-results/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: { ecmaVersion: 2022, sourceType: 'module' },
    rules: {
      // 未使用参数用下划线前缀显式忽略（与后端惯例一致）
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
  {
    // Node 侧脚本（契约生成、live 走查）
    files: ['**/*.mjs'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: NODE_GLOBALS,
    },
  },
)
