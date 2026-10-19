import { Routes, Route } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import Verify from './Verify'
import { useVerifyProduct, useProduct } from '@/hooks/useApi'
import { renderWithProviders } from '@/test/test-utils'

vi.mock('@/components/EvidenceTimeline', () => ({ default: () => <div>Recorded timeline</div> }))

vi.mock('@/hooks/useApi', () => ({
  useVerifyProduct: vi.fn(),
  useProduct: vi.fn(),
}))

function renderVerify() {
  window.history.replaceState({}, '', '/verify')
  return renderWithProviders(<Routes><Route path="/verify/:productId?" element={<Verify />} /></Routes>)
}

describe('Verify', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    vi.mocked(useVerifyProduct).mockImplementation((id: string) => {
      if (!id) {
        return { data: undefined, isLoading: false, error: null } as any
      }
      return {
        data: { is_registered: true, is_delivered: false, checkpoint_count: 5 },
        isLoading: false,
        error: null,
      } as any
    })

    vi.mocked(useProduct).mockImplementation((id: string) => {
      if (!id) {
        return { data: undefined, isLoading: false, error: null } as any
      }
      return {
        data: {
          product: {
            product_id: 'PROD-001',
            name: 'Widget',
            manufacturer_address: '0x1234567890123456789012345678901234567890',
            registered_at: '2024-01-15T10:00:00Z',
          },
        },
        isLoading: false,
        error: null,
      } as any
    })
  })

  it('renders search input and verify button', () => {
    renderVerify()

    expect(screen.getByPlaceholderText('Enter product ID')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /verify/i })).toBeInTheDocument()
  })

  it('shows initial helper state before search', () => {
    renderVerify()

    expect(screen.getByText('Enter a product ID to check its blockchain registration and recorded history.')).toBeInTheDocument()
  })

  it('displays verification result when product is authentic', async () => {
    renderVerify()

    const input = screen.getByPlaceholderText('Enter product ID')
    fireEvent.change(input, { target: { value: 'PROD-001' } })
    fireEvent.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => {
      expect(screen.getByText('Blockchain Registration Confirmed')).toBeInTheDocument()
      expect(screen.getByText('Verified')).toBeInTheDocument()
      // Checkpoint count appears twice (banner + details card)
      expect(screen.getAllByText('5')).toHaveLength(2)
    })
  })

  it('displays failure message for unregistered product', async () => {
    vi.mocked(useVerifyProduct).mockImplementation((id: string) => {
      if (!id) return { data: undefined, isLoading: false, error: null } as any
      return {
        data: { is_registered: false, is_delivered: false, checkpoint_count: 0 },
        isLoading: false,
        error: null,
      } as any
    })

    renderVerify()

    const input = screen.getByPlaceholderText('Enter product ID')
    fireEvent.change(input, { target: { value: 'FAKE-001' } })
    fireEvent.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => {
      expect(screen.getByText('Registration Not Confirmed')).toBeInTheDocument()
    })
  })
})
