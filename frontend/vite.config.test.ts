// @vitest-environment node
import { describe, it, expect } from 'vitest'
import config from './vite.config'

describe('vite.config.ts', () => {
  const resolved =
    typeof config === 'function'
      ? config({ command: 'build', mode: 'production' })
      : config

  type Group = { name: string; test: RegExp }

  const groups = (): Group[] =>
    ((resolved.build as any)?.rolldownOptions?.output?.codeSplitting?.groups ??
      []) as Group[]

  it('configures codeSplitting groups for expected vendor bundles (regression: FCP 11.46s)', () => {
    expect(resolved.build).toBeDefined()
    expect(groups().map(g => g.name)).toEqual([
      'react-vendor',
      'ui-vendor',
      'web3-vendor',
      'charts-vendor',
      'query-vendor',
    ])

    const reactVendor = groups().find(g => g.name === 'react-vendor')!
    expect(reactVendor.test.test('/repo/node_modules/react/index.js')).toBe(true)
    expect(reactVendor.test.test('/repo/node_modules/react-dom/client.js')).toBe(true)
    expect(
      reactVendor.test.test('/repo/node_modules/react-router-dom/dist/index.js')
    ).toBe(true)
  })

  it('extracts heavy libraries out of the initial chunk', () => {
    const matches = (id: string) => groups().some(g => g.test.test(id))

    expect(matches('/repo/node_modules/wagmi/dist/esm/index.js')).toBe(true)
    expect(matches('/repo/node_modules/viem/_esm/index.js')).toBe(true)
    expect(matches('/repo/node_modules/@rainbow-me/rainbowkit/dist/index.js')).toBe(true)
    expect(matches('/repo/node_modules/recharts/es6/index.js')).toBe(true)
    expect(matches('/repo/node_modules/@tanstack/react-query/build/index.js')).toBe(true)
    expect(matches('/repo/node_modules/@tanstack/query-core/build/index.js')).toBe(true)
    expect(matches('/repo/node_modules/framer-motion/dist/es/index.mjs')).toBe(true)
    expect(matches('/repo/node_modules/lucide-react/dist/esm/index.js')).toBe(true)
  })
})
