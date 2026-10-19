import { readFileSync } from 'node:fs'
export const policy = JSON.parse(
  readFileSync(new URL('./release_policy.json', import.meta.url), 'utf8'),
)
export class ReleaseRejected extends Error {}
export class ReleasePending extends Error {}

export async function github(path) {
  const headers = {
    Accept: 'application/vnd.github+json',
    'User-Agent': 'Veritras-release-gate',
    'X-GitHub-Api-Version': '2022-11-28',
  }
  if (process.env.GITHUB_RELEASE_TOKEN)
    headers.Authorization = `Bearer ${process.env.GITHUB_RELEASE_TOKEN}`
  try {
    const response = await fetch(
      `https://api.github.com/repos/${policy.repository}${path}`,
      {
        headers,
        signal: AbortSignal.timeout(10_000),
        redirect: 'error',
      },
    )
    if (!response.ok) throw new Error('Unavailable')
    return await response.json()
  } catch {
    throw new ReleasePending('GitHub release checks unavailable')
  }
}

export async function assess(commit, get = github) {
  if (!/^[0-9a-f]{40}$/.test(commit ?? ''))
    throw new ReleaseRejected('A full production Git commit is required')
  const query = new URLSearchParams({
    head_sha: commit,
    event: 'push',
    branch: policy.branch,
    per_page: '100',
  })
  const data = await get(`/actions/runs?${query}`)
  if (!Array.isArray(data?.workflow_runs))
    throw new ReleaseRejected('Invalid GitHub workflow response')
  const evidence = []
  for (const workflow of policy.workflows) {
    const candidates = data.workflow_runs.filter(
      (r) =>
        r.head_sha === commit &&
        r.path === workflow.path &&
        r.event === 'push' &&
        r.head_branch === policy.branch &&
        r.head_repository?.full_name?.toLowerCase() ===
          policy.repository.toLowerCase(),
    )
    if (!candidates.length)
      throw new ReleasePending(
        `Required main-push workflow is missing: ${workflow.path}`,
      )
    const run = candidates.sort(
      (a, b) => b.id - a.id || b.run_attempt - a.run_attempt,
    )[0]
    if (
      !Number.isSafeInteger(run.id) ||
      !Number.isSafeInteger(run.run_attempt) ||
      run.run_attempt < 1
    )
      throw new ReleaseRejected('Invalid workflow identity')
    if (run.status !== 'completed')
      throw new ReleasePending(`Waiting for ${workflow.path}`)
    if (run.conclusion !== 'success')
      throw new ReleaseRejected(`Required workflow failed: ${workflow.path}`)
    const jobs = await get(
      `/actions/runs/${run.id}/attempts/${run.run_attempt}/jobs?per_page=100`,
    )
    if (!Array.isArray(jobs?.jobs) || jobs.total_count > 100)
      throw new ReleaseRejected('Invalid or truncated job response')
    for (const name of workflow.jobs) {
      const matching = jobs.jobs.filter((j) => j.name === name)
      if (
        matching.length !== 1 ||
        matching[0].status !== 'completed' ||
        matching[0].conclusion !== 'success' ||
        matching[0].head_sha !== commit
      )
        throw new ReleaseRejected(
          `Required job did not succeed on this commit: ${name}`,
        )
    }
    evidence.push({
      workflow: workflow.path,
      run_id: run.id,
      attempt: run.run_attempt,
    })
  }
  return {
    commit,
    repository: policy.repository,
    branch: policy.branch,
    workflows: evidence,
  }
}

export async function waitForRelease(
  commit,
  {
    deadline = 900_000,
    interval = 60_000,
    get = github,
    clock = Date.now,
    pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  } = {},
) {
  const end = clock() + deadline
  for (;;) {
    try {
      return await assess(commit, get)
    } catch (error) {
      if (!(error instanceof ReleasePending)) throw error
      const remaining = end - clock()
      if (remaining <= 0)
        throw new ReleaseRejected('Release checks unavailable before deadline')
      console.log(error.message)
      await pause(Math.min(interval, remaining))
    }
  }
}

export async function backendCommit(commit, get = github) {
  const commits = await get(
    `/commits?${new URLSearchParams({ sha: commit, path: 'backend', per_page: '1' })}`,
  )
  const backend = commits?.[0]?.sha
  if (!/^[0-9a-f]{40}$/.test(backend ?? ''))
    throw new ReleaseRejected('Cannot identify compatible backend commit')
  return backend
}

export async function waitForApi(
  origin,
  commits,
  {
    deadline = 300_000,
    interval = 10_000,
    get = fetch,
    clock = Date.now,
    pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  } = {},
) {
  const end = clock() + deadline
  for (;;) {
    try {
      const response = await get(`${origin}/health/ready`, {
        signal: AbortSignal.timeout(5000),
        redirect: 'error',
      })
      const body = await response.json()
      if (
        response.ok &&
        body.status === 'ready' &&
        body.database === 'connected' &&
        body.environment === 'production' &&
        body.chain_id === 11155111 &&
        body.indexer?.enabled === false &&
        commits.includes(body.release_commit)
      )
        return body.release_commit
    } catch {
      /* A stale/missing/unavailable API is never compatible evidence. */
    }
    const remaining = end - clock()
    if (remaining <= 0)
      throw new ReleaseRejected(
        'Compatible production API was not ready before deadline',
      )
    await pause(Math.min(interval, remaining))
  }
}
