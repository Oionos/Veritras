// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { apiMatchesPolicy, environmentPolicy } from './environment-policy.mjs'

const expected = environmentPolicy.environments.testing
function body() {
  return {
    status: 'ready',
    database: 'connected',
    environment: 'testing',
    chain_id: 11155111,
    indexer: {
      enabled: true,
      ready: true,
      status: 'current',
      chain_id: 11155111,
      registry_address: expected.registry,
      tracker_address: expected.tracker,
      start_block: expected.start_block,
      confirmation_policy: 'depth',
      confirmations: 12,
      cursor_storage: 'database',
      chain_head: 120,
      target_head: 108,
      last_processed_block: 108,
      lag_blocks: 0,
      max_lag_blocks: 0,
      success_age_seconds: 1,
      stale_after_seconds: 120,
      head_age_seconds: 2,
      head_stale_after_seconds: 300,
    },
  }
}

describe('strict environment readiness policy', () => {
  it('accepts the exact healthy enabled scope', () => {
    expect(apiMatchesPolicy(body(), expected, 'testing')).toBe(true)
  })
  it.each([
    { status: 'catching_up' },
    { ready: false },
    { enabled: false },
    { confirmations: 0 },
    { registry_address: '0x' + '1'.repeat(40) },
    { tracker_address: '0x' + '2'.repeat(40) },
    { start_block: 0 },
    { lag_blocks: 1 },
    { last_processed_block: 107 },
    { target_head: 120 },
    { success_age_seconds: 120 },
    { success_age_seconds: NaN },
    { head_age_seconds: 300 },
    { head_stale_after_seconds: 0 },
    { cursor_storage: 'file' },
    { chain_id: 31337 },
  ])('rejects unhealthy or wrong enabled evidence %j', (change) => {
    const observed = body()
    Object.assign(observed.indexer, change)
    expect(apiMatchesPolicy(observed, expected, 'testing')).toBe(false)
  })
  it('rejects the wrong environment and missing approved anchor', () => {
    expect(apiMatchesPolicy(body(), expected)).toBe(false)
    expect(
      apiMatchesPolicy(body(), { ...expected, start_block: null }, 'testing'),
    ).toBe(false)
  })
  it('keeps disabled production strict', () => {
    const production = environmentPolicy.environments.production
    const observed = body()
    observed.environment = 'production'
    Object.assign(observed.indexer, {
      status: 'disabled',
      enabled: false,
      registry_address: production.registry,
      tracker_address: production.tracker,
    })
    expect(apiMatchesPolicy(observed, production)).toBe(true)
    observed.indexer.enabled = true
    expect(apiMatchesPolicy(observed, production)).toBe(false)
  })
})
