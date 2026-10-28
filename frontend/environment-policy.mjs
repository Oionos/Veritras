import { readFileSync } from 'node:fs'

export const environmentPolicy = JSON.parse(
  readFileSync(new URL('./environment_policy.json', import.meta.url), 'utf8'),
)

if (
  environmentPolicy.version !== 1 ||
  Object.keys(environmentPolicy.environments).sort().join(',') !==
    'production,testing'
)
  throw new Error('Invalid environment policy')

for (const expected of Object.values(environmentPolicy.environments)) {
  const origin = new URL(expected.api_origin)
  if (
    origin.protocol !== 'https:' ||
    origin.origin !== expected.api_origin ||
    !['enabled', 'disabled'].includes(expected.indexer_mode) ||
    !Number.isSafeInteger(expected.chain_id) ||
    expected.chain_id <= 0 ||
    !Number.isSafeInteger(expected.confirmations) ||
    expected.confirmations < 0 ||
    expected.confirmations > 256 ||
    ![expected.registry, expected.tracker].every((value) =>
      /^0x[0-9a-fA-F]{40}$/.test(value),
    ) ||
    (expected.start_block !== null &&
      (!Number.isSafeInteger(expected.start_block) || expected.start_block < 0))
  )
    throw new Error('Invalid environment policy')
}

export function apiMatchesPolicy(body, expected, environment = 'production') {
  const indexer = body?.indexer
  if (
    body?.status !== 'ready' ||
    body.database !== 'connected' ||
    body.environment !== environment ||
    body.chain_id !== expected.chain_id ||
    !indexer ||
    indexer.chain_id !== expected.chain_id ||
    indexer.enabled !== (expected.indexer_mode === 'enabled') ||
    indexer.confirmation_policy !== 'depth' ||
    indexer.confirmations !== expected.confirmations ||
    indexer.registry_address?.toLowerCase() !==
      expected.registry.toLowerCase() ||
    indexer.tracker_address?.toLowerCase() !== expected.tracker.toLowerCase() ||
    (expected.start_block !== null &&
      indexer.start_block !== expected.start_block)
  )
    return false
  if (expected.indexer_mode === 'disabled') return indexer.status === 'disabled'
  if (expected.indexer_mode !== 'enabled' || expected.start_block === null)
    return false
  const {
    chain_head: head,
    target_head: target,
    last_processed_block: cursor,
    lag_blocks: lag,
    max_lag_blocks: limit,
    success_age_seconds: age,
    stale_after_seconds: stale,
    head_age_seconds: headAge,
    head_stale_after_seconds: headStale,
  } = indexer
  return (
    indexer.status === 'current' &&
    indexer.ready === true &&
    indexer.cursor_storage === 'database' &&
    [head, target, cursor, lag, limit].every(
      (n) => Number.isSafeInteger(n) && n >= 0,
    ) &&
    target === Math.max(0, head - expected.confirmations) &&
    cursor === target &&
    lag === 0 &&
    [age, stale, headAge, headStale].every(
      (n) => typeof n === 'number' && Number.isFinite(n),
    ) &&
    age >= 0 &&
    age < stale &&
    headAge >= 0 &&
    headAge < headStale
  )
}
