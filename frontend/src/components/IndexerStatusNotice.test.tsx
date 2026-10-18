import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import IndexerStatusNotice from './IndexerStatusNotice'
import { useIndexerHealth } from '@/hooks/useIndexerHealth'
vi.mock('@/hooks/useIndexerHealth', () => ({ useIndexerHealth: vi.fn() }))
const mock = (status: string, database = 'connected') =>
  vi
    .mocked(useIndexerHealth)
    .mockReturnValue({
      data: { database, indexer: { status } },
      isError: false,
    } as any)
describe('synchronization notice', () => {
  beforeEach(() => vi.clearAllMocks())
  it('stays hidden while current or initially loading', () => {
    mock('current')
    const view = render(<IndexerStatusNotice />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    vi.mocked(useIndexerHealth).mockReturnValue({
      data: undefined,
      isError: false,
    } as any)
    view.rerender(<IndexerStatusNotice />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
  it.each(['starting', 'catching_up'])(
    'explains %s without implementation details',
    (status) => {
      mock(status)
      render(<IndexerStatusNotice />)
      expect(screen.getByRole('status')).toHaveTextContent(
        'activity is syncing',
      )
    },
  )
  it('makes intentionally paused indexing visible', () => {
    mock('disabled')
    render(<IndexerStatusNotice />)
    expect(screen.getByRole('status')).toHaveTextContent('updates are paused')
  })
  it.each(['degraded', 'not_started', 'stopped', 'stopping'])(
    'does not imply current data for %s',
    (status) => {
      mock(status)
      render(<IndexerStatusNotice />)
      expect(screen.getByRole('status')).toHaveTextContent(
        'updates are delayed',
      )
    },
  )
  it('explains database and health request failures safely', () => {
    mock('current', 'timed_out')
    const view = render(<IndexerStatusNotice />)
    expect(screen.getByRole('status')).toHaveTextContent(
      'Live data is temporarily unavailable',
    )
    vi.mocked(useIndexerHealth).mockReturnValue({ isError: true } as any)
    view.rerender(<IndexerStatusNotice />)
    expect(screen.getByRole('status')).toHaveTextContent(
      'Synchronization status is unavailable',
    )
  })
})
