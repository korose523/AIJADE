import { getTableColumns, getTableName, is } from 'drizzle-orm'
import { getTableConfig, PgDialect, PgTable } from 'drizzle-orm/pg-core'

import * as longTermMemorySchema from './long-term-memory'
import * as memorySchema from './memory-v9'

/**
 * 从 drizzle schema **生成** PGlite（内存版 Postgres）用的物理 DDL。
 *
 * ## 为什么需要它（这是一个结构性问题，不是工具性便利）
 *
 * 本仓此前有 **9 处**各自手抄一份 `CREATE TABLE`：3 个验收脚本 + 6 个 `*.test.ts`。
 * 每一份都声称"与 drizzle schema 逐列对应"，但手抄的 DDL **不参与任何类型检查**，
 * schema 加列它不会跟着动。后果不是理论上的：
 *
 * - `apps/server/scripts/verify-v9-events-http.ts` 的 `events` 表少了 8 列
 *   （`origin_device` / `privacy_level` / `evidence_refs` / `causal_context_refs` /
 *   `risk_score` / `tick` / `causality` / `core_state_node`），且完全没有 `render_traces` 表 ——
 *   于是该脚本的**第一个断言就失败**（`persona.render_requested` 期望 201，实测 500），
 *   而它既不在 `tsc` 覆盖内、也不在 CI 里，失效长期无人发现。
 * - 同一形状抄多份时**正确性取决于哪一份最近被改过**：三份里只有一份是最新的。
 *
 * 这与 `events.ts` 头注里记的那次「信封在 6 处各抄一遍」是同一类结构性问题：
 * **同一形状的多个副本，必然漂移。** 解法也一样 —— 让形状只有一个来源。
 *
 * ## 覆盖范围
 *
 * 只覆盖本项目用于 PGlite 验收的 schema。列类型全集仅 6 种
 * （PgText / PgJsonb / PgTimestamp / PgInteger / PgReal / PgArray(PgText)）。
 * 若未来引入新类型，本模块**抛错**而不是静默生成错误的 DDL —— 让问题在生成时就炸，
 * 而不是伪装成下游的一个 500。
 */

/** 列元数据 → SQL 类型片段。未知类型直接抛错（fail-fast，不静默降级）。 */
function sqlTypeFor(column: any): string {
  switch (column.columnType) {
    case 'PgText':
      return 'text'
    case 'PgJsonb':
      return 'jsonb'
    case 'PgTimestamp':
      return 'timestamp'
    case 'PgInteger':
      return 'integer'
    case 'PgReal':
      return 'real'
    case 'PgArray': {
      const base = column.baseColumn?.columnType
      if (base !== 'PgText')
        throw new Error(`[pglite-ddl] 不支持的数组基类型：${String(base)}（列 ${column.name}）`)
      return 'text[]'
    }
    default:
      throw new Error(`[pglite-ddl] 不支持的列类型：${String(column.columnType)}（列 ${column.name}）。`
        + '请在此显式补充映射，不要让它静默生成错误 DDL。')
  }
}

/**
 * 默认值片段（无前导空格；不可用时返回空串）。
 *
 * 刻意**只**为"数据库层默认值"生成 DEFAULT：
 * - `PgTimestamp` + hasDefault → `DEFAULT NOW()`（对应 drizzle `.defaultNow()`）
 * - `PgArray` + hasDefault → `DEFAULT '{}'`
 * - `PgReal` / `PgInteger` + hasDefault → `DEFAULT 0`
 *
 * `text` 列的 `hasDefault` 来自 `$defaultFn(() => nanoid())` —— 那是**应用层**默认值
 * （id 由代码生成），数据库不需要也不应有 DEFAULT，故 text 一律不生成。
 */
function defaultClauseFor(column: any): string {
  if (!column.hasDefault || column.primary || column.columnType === 'PgText')
    return ''
  switch (column.columnType) {
    case 'PgTimestamp':
      return 'DEFAULT NOW()'
    case 'PgArray':
      return `DEFAULT '{}'`
    case 'PgReal':
    case 'PgInteger':
      return 'DEFAULT 0'
    default:
      throw new Error(`[pglite-ddl] 列 ${column.name} 有默认值但类型 ${String(column.columnType)} 无映射规则`)
  }
}

/** 枚举列 → CHECK 约束（无前导空格；非枚举列返回空串）。 */
function checkClauseFor(column: any): string {
  const values: unknown = column.enumValues
  if (!Array.isArray(values) || values.length === 0)
    return ''
  const list = values.map(v => `'${String(v)}'`).join(',')
  return `CHECK ("${column.name}" IN (${list}))`
}

const pgDialect = new PgDialect()

/** 表级 CHECK 约束片段（schema 经 `check()` 登记的表级约束 → DDL 文本）。 */
function tableCheckClausesFor(table: PgTable): string[] {
  const checks = getTableConfig(table as never).checks as readonly {
    name: string
    value: { } | undefined
  }[]
  return (checks ?? []).map((c) => {
    if (!c.value)
      throw new Error(`[pglite-ddl] 表级 CHECK "${c.name}" 缺少 SQL 表达式 —— schema 登记不完整，fail-fast`)
    const rendered = pgDialect.sqlToQuery(c.value as never)
    if (rendered.params.length > 0)
      throw new Error(`[pglite-ddl] 表级 CHECK "${c.name}" 含绑定参数，无法生成为静态 DDL —— fail-fast`)
    return `    CONSTRAINT "${c.name}" CHECK (${rendered.sql})`
  })
}

/** 生成单张表的 `CREATE TABLE` 语句。 */
export function buildCreateTableSql(table: PgTable): string {
  const cols = getTableColumns(table as never) as Record<string, any>
  const body = Object.values(cols).map((column) => {
    const clauses: string[] = []
    if (column.primary)
      clauses.push('PRIMARY KEY')
    if (column.notNull && !column.primary)
      clauses.push('NOT NULL')
    if (column.isUnique && !column.primary)
      clauses.push('UNIQUE')
    const defaultClause = defaultClauseFor(column)
    if (defaultClause)
      clauses.push(defaultClause)
    const checkClause = checkClauseFor(column)
    if (checkClause)
      clauses.push(checkClause)
    return `    ${[`"${column.name}"`, sqlTypeFor(column), ...clauses].join(' ')}`
  })
  // 表级约束（CHECK 等）跟在列定义之后。注意：这里按 drizzle schema 语义生成为
  // **立即校验**的约束（建表时即对数据生效）；真实库的迁移侧（drizzle/0025）对
  // 存量行用 NOT VALID 放行，两者语义差异见 0025 头注。
  body.push(...tableCheckClausesFor(table))
  return `  CREATE TABLE "${getTableName(table)}" (\n${body.join(',\n')}\n  );`
}

/** 生成一组表的完整 DDL 脚本，可直接 `client.exec()`。 */
export function buildDdl(tables: readonly PgTable[]): string {
  return tables.map(buildCreateTableSql).join('\n')
}

/** 从某个 schema 模块中取出全部 drizzle 表（顺序即声明顺序）。 */
function tablesOf(module: Record<string, unknown>): PgTable[] {
  const tables: PgTable[] = []
  for (const value of Object.values(module)) {
    // 用 if-窄化而不是显式类型谓词：`value is PgTable` 会让谓词类型比参数类型更宽，
    // tsc 直接报 TS2677。
    if (is(value, PgTable) && typeof value === 'object')
      tables.push(value)
  }
  return tables
}

/** `src/schemas/memory-v9.ts` 中登记的全部表。 */
export function memoryV9Tables(): PgTable[] {
  return tablesOf(memorySchema)
}

/** `src/schemas/long-term-memory.ts` 中登记的全部表。 */
export function longTermMemoryTables(): PgTable[] {
  return tablesOf(longTermMemorySchema)
}

/** v9/v10 内核表 + 长期记忆表的合集（persona / intent 相关测试需要两者）。 */
export function memoryAndLongTermTables(): PgTable[] {
  return [...memoryV9Tables(), ...longTermMemoryTables()]
}

/** v9/v10 内核表的 DDL。 */
export function buildMemoryV9Ddl(): string {
  return buildDdl(memoryV9Tables())
}

/** v9/v10 内核表 + 长期记忆表的 DDL。 */
export function buildMemoryAndLongTermDdl(): string {
  return buildDdl(memoryAndLongTermTables())
}

/** 最小 PGlite 客户端接口（只用到 `query`，便于测试替身与真库共用）。 */
export interface PgliteQueryable {
  query: <T>(sql: string) => Promise<{ rows: T[] }>
}

/**
 * 环境自检：确认生成的 DDL 真的建出了给定表的**全部列**。
 *
 * 为什么必须复核：本模块本身就是"用元数据替代手抄"的修复，若它自己悄悄漏了东西，
 * 失败形态会和修复前一模一样 —— **下游 500 而非清晰报错**。
 * 故建表后立刻向 `information_schema` 复核一次列数。
 */
export async function assertSchemaMatchesDrizzle(
  client: PgliteQueryable,
  tables: readonly PgTable[],
): Promise<void> {
  for (const table of tables) {
    const tableName = getTableName(table)
    const expected = Object.keys(getTableColumns(table as never)).length
    const { rows } = await client.query<{ column_name: string }>(
      `SELECT column_name FROM information_schema.columns WHERE table_name = '${tableName}'`,
    )
    if (rows.length !== expected) {
      throw new Error(`[pglite-ddl] 表 ${tableName} 列数不符：schema ${expected} 列，实际建出 ${rows.length} 列。`
        + 'DDL 生成器已漂移，必须修复而不是忽略。')
    }
  }
}

/** 内核表的建表 + 自检（验收脚本的常用组合）。 */
export async function initMemoryV9Schema(client: PgliteQueryable): Promise<void> {
  await (client as unknown as { exec: (sql: string) => Promise<unknown> }).exec(buildMemoryV9Ddl())
  await assertSchemaMatchesDrizzle(client, memoryV9Tables())
}
