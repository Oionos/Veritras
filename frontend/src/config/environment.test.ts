// @vitest-environment node
import { describe, expect, it } from 'vitest'
import {
  resolveEnvironment,
  connectSources,
  LIVE_API_ORIGIN,
  LIVE_CONTRACTS,
} from './environment'
import { toProductBytes32 } from '../utils/productId'

const testing = {
  VITE_APP_ENV: 'testing',
  VITE_API_URL: 'https://veritras-api-testing.onrender.com',
  VITE_PRODUCT_REGISTRY_CONTRACT: `0x${'1'.repeat(40)}`,
  VITE_SHIPMENT_TRACKER_CONTRACT: `0x${'2'.repeat(40)}`,
}

describe('testing isolation', () => {
  it('rejects the live API and either live contract in testing', () => {
    expect(() =>
      resolveEnvironment({ ...testing, VITE_API_URL: LIVE_API_ORIGIN }),
    ).toThrow(/live API/)
    for (const address of LIVE_CONTRACTS) {
      expect(() =>
        resolveEnvironment({
          ...testing,
          VITE_PRODUCT_REGISTRY_CONTRACT: address,
        }),
      ).toThrow(/live API/)
      expect(() =>
        resolveEnvironment({
          ...testing,
          VITE_SHIPMENT_TRACKER_CONTRACT: address,
        }),
      ).toThrow(/live API/)
    }
  })
  it('rejects missing preview configuration even in CI', () => {
    expect(() => resolveEnvironment({}, { preview: true, ci: true })).toThrow(
      /Preview/,
    )
    expect(() =>
      resolveEnvironment(
        { VITE_APP_ENV: 'testing' },
        { preview: true, ci: true },
      ),
    ).toThrow(/Explicit/)
  })
  it('allows a scoped hosted preview and permits only its API in CSP', () => {
    const env = resolveEnvironment(testing, { preview: true })
    expect(connectSources(env)).toContain(testing.VITE_API_URL)
    expect(connectSources(env)).not.toContain(LIVE_API_ORIGIN)
  })
  it('supports local chain 31337 but rejects it for hosted previews', () => {
    const env = {
      ...testing,
      VITE_API_URL: 'http://localhost:18000',
      VITE_CHAIN_ID: '31337',
      VITE_RPC_URL: 'http://localhost:18545',
    }
    expect(resolveEnvironment(env).chainId).toBe(31337)
    expect(() => resolveEnvironment(env, { preview: true })).toThrow(/HTTPS/)
  })
  it('keeps an indexed bytes32 ID stable and bounds UTF-8 IDs', () => {
    const id = toProductBytes32('PROD-TEST')
    expect(toProductBytes32(id)).toBe(id)
    expect(() => toProductBytes32('a'.repeat(33))).toThrow(/32 bytes/)
  })
})
