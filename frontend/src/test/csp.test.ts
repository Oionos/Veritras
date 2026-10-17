import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

describe('Content-Security-Policy', () => {
  it('contains all required directives and domains in frontend/index.html', () => {
    // Arrange
    const htmlPath = resolve(__dirname, '../../index.html')
    const html = readFileSync(htmlPath, 'utf-8')

    // Act — parse the CSP meta tag
    const cspMatch = html.match(
      /<meta\s+[^>]*http-equiv=["']?Content-Security-Policy["']?\s+[^>]*content="([^"]+)"/i
    )
    expect(cspMatch, 'CSP meta tag not found in index.html').toBeTruthy()

    const cspString = cspMatch![1]
    const directives: Record<string, string> = {}

    cspString.split(';').forEach((part) => {
      const trimmed = part.trim()
      if (!trimmed) return
      const spaceIdx = trimmed.indexOf(' ')
      if (spaceIdx === -1) {
        directives[trimmed] = ''
      } else {
        directives[trimmed.slice(0, spaceIdx)] = trimmed.slice(spaceIdx + 1).trim()
      }
    })

    // Assert — connect-src
    expect(directives['connect-src']).toContain("'self'")
    expect(directives['connect-src']).toContain('__VERITRAS_CONNECT_SOURCES__')
    expect(directives['connect-src']).not.toContain('chainlens-4qvy.onrender.com')
    expect(directives['connect-src']).toContain('https://*.walletconnect.com')
    expect(directives['connect-src']).toContain('https://*.walletconnect.org')
    expect(directives['connect-src']).toContain('wss://*.walletconnect.com')
    expect(directives['connect-src']).toContain('wss://*.walletconnect.org')
    expect(directives['connect-src']).toContain('https://*.infura.io')
    expect(directives['connect-src']).toContain('https://*.web3modal.org')
    expect(directives['connect-src']).toContain('https://*.rpc.thirdweb.com')
    expect(directives['connect-src']).toContain('https://api.vercel.com')

    // Assert — script-src (must never contain wildcard)
    expect(directives['script-src']).toContain("'self'")
    expect(directives['script-src']).toContain("'unsafe-inline'")
    expect(directives['script-src']).not.toContain('*')

    // Assert — img-src
    expect(directives['img-src']).toContain('blob:')

    // Assert — frame-src
    expect(directives['frame-src']).toContain('https://*.walletconnect.com')
    expect(directives['frame-src']).toContain('https://*.walletconnect.org')

    // Assert — manifest-src
    expect(directives['manifest-src']).toContain("'self'")
  })
})
