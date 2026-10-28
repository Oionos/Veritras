import { readFileSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { waitForRelease, backendCommit, waitForApi } from './release-gate.mjs'
import { environmentPolicy } from './environment-policy.mjs'

const env = { ...process.env }
// Public browser configuration for the existing live deployment. Preview builds
// still require their own isolated services and never receive these defaults.
if (env.VERCEL_ENV === 'production') {
  const defaults = JSON.parse(
    readFileSync(
      new URL('./deployment.production.json', import.meta.url),
      'utf8',
    ),
  )
  for (const [key, value] of Object.entries(defaults)) {
    if (!env[key]) env[key] = value
  }
}

let evidence
if (env.VERCEL_ENV === 'production') {
  if (
    env.VERCEL_GIT_COMMIT_REF !== 'main' ||
    env.VITE_API_URL !== environmentPolicy.environments.production.api_origin
  )
    throw new Error('Production must use main and its reviewed API')
  evidence = await waitForRelease(env.VERCEL_GIT_COMMIT_SHA)
  const compatible = await backendCommit(env.VERCEL_GIT_COMMIT_SHA)
  evidence.backend_commit = await waitForApi(env.VITE_API_URL, [
    env.VERCEL_GIT_COMMIT_SHA,
    compatible,
  ])
}
const result = spawnSync('npm', ['run', 'build'], { env, stdio: 'inherit' })
if (result.error) throw result.error
if (result.status === 0)
  writeFileSync(
    new URL('./dist/release.json', import.meta.url),
    JSON.stringify({
      environment: env.VERCEL_ENV ?? 'local',
      commit: env.VERCEL_GIT_COMMIT_SHA ?? null,
      ci: evidence ?? null,
    }) + '\n',
  )
process.exit(result.status ?? 1)
