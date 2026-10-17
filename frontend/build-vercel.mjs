import { readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'

const env = { ...process.env }
// Public browser configuration for the existing live deployment. Preview builds
// still require their own isolated services and never receive these defaults.
if (env.VERCEL_ENV === 'production') {
  const defaults = JSON.parse(
    readFileSync(new URL('./deployment.production.json', import.meta.url), 'utf8'),
  )
  for (const [key, value] of Object.entries(defaults)) {
    if (!env[key]) env[key] = value
  }
}

const result = spawnSync('npm', ['run', 'build'], { env, stdio: 'inherit' })
if (result.error) throw result.error
process.exit(result.status ?? 1)
