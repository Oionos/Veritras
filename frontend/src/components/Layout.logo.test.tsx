import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import Layout from './Layout'

vi.mock('@/hooks/useSSE', () => ({ useChainEvents: vi.fn() }))

vi.mock('./ConnectAndAuth', () => ({
  default: () => <button>Connect Wallet</button>,
}))

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<div>Dashboard body</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  )
}

describe('Layout logo', () => {
  it('uses the generated Veritras crystal logo in the navbar brand', () => {
    renderLayout()

    const logo = screen.getByRole('img', { name: 'Veritras crystal logo' })

    expect(logo).toHaveAttribute('src', expect.stringContaining('veritras-crystal-logo-512.png'))
  })
})
