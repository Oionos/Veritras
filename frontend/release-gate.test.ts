// @vitest-environment node
import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  assess,
  policy,
  ReleaseRejected,
  ReleasePending,
  waitForRelease,
  waitForApi,
  backendCommit,
  github,
} from './release-gate.mjs'
afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})
const sha = 'a'.repeat(40)
function fixture() {
  const runs = policy.workflows.map((w, i) => ({
    id: i + 1,
    run_attempt: 1,
    head_sha: sha,
    path: w.path,
    event: 'push',
    head_branch: 'main',
    head_repository: { full_name: 'Oionos/Veritras' },
    status: 'completed',
    conclusion: 'success',
  }))
  const jobs = policy.workflows.map((w) => ({
    total_count: w.jobs.length,
    jobs: w.jobs.map((name) => ({
      name,
      status: 'completed',
      conclusion: 'success',
      head_sha: sha,
    })),
  }))
  const get = vi.fn(async (path) =>
    path.startsWith('/actions/runs?')
      ? { workflow_runs: runs }
      : jobs[Number(path.split('/')[3]) - 1],
  )
  return { runs, jobs, get }
}
describe('production release admission', () => {
  it.each([undefined, 'synthetic-read-only-token'])(
    'uses optional server-only credential %s',
    async (token) => {
      vi.stubEnv('GITHUB_RELEASE_TOKEN', token)
      const get = vi.fn(async () => ({
        ok: true,
        json: async () => ({ workflow_runs: [] }),
      }))
      vi.stubGlobal('fetch', get)
      await github('/actions/runs')
      expect(get.mock.calls[0][0]).toBe(
        'https://api.github.com/repos/Oionos/Veritras/actions/runs',
      )
      expect(get.mock.calls[0][1].headers.Authorization).toBe(
        token ? `Bearer ${token}` : undefined,
      )
    },
  )
  it('does not expose a credential when the provider request fails', async () => {
    vi.stubEnv('GITHUB_RELEASE_TOKEN', 'synthetic-private-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('synthetic-private-token')
      }),
    )
    await expect(github('/actions/runs')).rejects.toThrow(
      'GitHub release checks unavailable',
    )
  })
  it('requires exact main push and all real jobs', async () => {
    const { get } = fixture()
    expect((await assess(sha, get)).commit).toBe(sha)
    await expect(assess('short', get)).rejects.toBeInstanceOf(ReleaseRejected)
  })
  it.each(['failure', 'cancelled', 'skipped', 'neutral', null])(
    'rejects workflow result %s',
    async (result) => {
      const { runs, get } = fixture()
      runs[0].conclusion = result
      await expect(assess(sha, get)).rejects.toBeInstanceOf(ReleaseRejected)
    },
  )
  it.each(['event', 'head_sha', 'head_branch', 'path', 'head_repository'])(
    'does not trust a mismatched %s',
    async (key) => {
      const { runs, get } = fixture()
      runs[0][key] =
        key === 'head_repository' ? { full_name: 'attacker/repo' } : 'wrong'
      await expect(assess(sha, get)).rejects.toBeInstanceOf(ReleasePending)
    },
  )
  it.each([
    'missing',
    'duplicate',
    'wrong_sha',
    'failure',
    'skipped',
    'truncated',
  ])('rejects %s jobs', async (mode) => {
    const { jobs, get } = fixture()
    if (mode === 'missing') jobs[0].jobs.shift()
    else if (mode === 'duplicate') jobs[0].jobs.push({ ...jobs[0].jobs[0] })
    else if (mode === 'wrong_sha') jobs[0].jobs[0].head_sha = 'b'.repeat(40)
    else if (mode === 'truncated') jobs[0].total_count = 101
    else jobs[0].jobs[0].conclusion = mode
    await expect(assess(sha, get)).rejects.toBeInstanceOf(ReleaseRejected)
  })
  it('will not substitute old successful runs for a new failure', async () => {
    const { runs, get } = fixture()
    runs.push({ ...runs[0], id: 3, conclusion: 'failure' })
    await expect(assess(sha, get)).rejects.toBeInstanceOf(ReleaseRejected)
  })
  it('waits only within a bounded deadline', async () => {
    let now = 0
    await expect(
      waitForRelease(sha, {
        deadline: 3,
        interval: 1,
        get: async () => {
          throw new ReleasePending('unavailable')
        },
        clock: () => now,
        pause: async (n) => {
          now += n
        },
      }),
    ).rejects.toBeInstanceOf(ReleaseRejected)
    expect(now).toBe(3)
  })
  it('can admit after pending work finishes', async () => {
    const { runs, get } = fixture()
    runs[0].status = 'in_progress'
    expect(
      (
        await waitForRelease(sha, {
          get,
          pause: async () => {
            runs[0].status = 'completed'
          },
        })
      ).commit,
    ).toBe(sha)
  })
  it('uses the last backend commit for frontend-only changes', async () => {
    expect(
      await backendCommit(sha, async () => [{ sha: 'b'.repeat(40) }]),
    ).toBe('b'.repeat(40))
    await expect(backendCommit(sha, async () => [])).rejects.toBeInstanceOf(
      ReleaseRejected,
    )
  })
  it('admits only the correct ready production API', async () => {
    const body = {
      status: 'ready',
      database: 'connected',
      environment: 'production',
      chain_id: 11155111,
      indexer: { enabled: false },
      release_commit: sha,
    }
    const get = async () => ({ ok: true, json: async () => body })
    expect(await waitForApi('https://example.com', [sha], { get })).toBe(sha)
    for (const change of [
      { environment: 'testing' },
      { release_commit: 'b'.repeat(40) },
      { indexer: { enabled: true } },
      { chain_id: 31337 },
      { database: 'disconnected' },
    ]) {
      let now = 0
      await expect(
        waitForApi('https://example.com', [sha], {
          deadline: 1,
          interval: 1,
          clock: () => now,
          pause: async (n) => {
            now += n
          },
          get: async () => ({
            ok: true,
            json: async () => ({ ...body, ...change }),
          }),
        }),
      ).rejects.toBeInstanceOf(ReleaseRejected)
    }
  })
})
