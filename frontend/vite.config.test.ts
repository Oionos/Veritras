// @vitest-environment node
import { describe, it, expect } from 'vitest'
import config from './vite.config'

describe('vite.config.ts', () => {
  const resolved =
    typeof config === 'function'
      ? config({ command: 'build', mode: 'production' })
      : config

  it('exports manualChunks with expected vendor bundles (regression: FCP 11.46s)', () => {
    expect(resolved.build).toBeDefined()
    expect(resolved.build?.rollupOptions).toBeDefined()
    expect(resolved.build?.rollupOptions?.output).toBeDefined()

    const output = resolved.build!.rollupOptions!.output as any
    expect(output.manualChunks).toBeDefined()

    const chunks = output.manualChunks

    expect(chunks['react-vendor']).toEqual([
      'react',
      'react-dom',
      'react-router-dom',
    ])
    expect(chunks['ui-vendor']).toEqual(['framer-motion', 'lucide-react'])
    expect(chunks['web3-vendor']).toEqual([
      'wagmi',
      'viem',
      '@rainbow-me/rainbowkit',
    ])
    expect(chunks['charts-vendor']).toEqual(['recharts'])
    expect(chunks['query-vendor']).toEqual(['@tanstack/react-query'])
  })

  it('extracts heavy libraries out of the initial chunk', () => {
    const output = resolved.build!.rollupOptions!.output as any
    const chunks = output.manualChunks

    const allVendors = Object.values(chunks).flat() as string[]
    expect(allVendors.length).toBeGreaterThan(0)

    // Key heavy libraries that were bloating the initial chunk
    expect(allVendors).toContain('react')
    expect(allVendors).toContain('react-dom')
    expect(allVendors).toContain('wagmi')
    expect(allVendors).toContain('recharts')
    expect(allVendors).toContain('@tanstack/react-query')
  })
})
