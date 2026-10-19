import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import { ProductCombobox, filterProducts } from '@/components/ui/ProductCombobox'
import type { Product } from '@/types'

// ─── Mutable mock state ────────────────────────────────────────────────────────

const mockProductListReturn: {
  data: { items: Product[]; total: number } | undefined
  isLoading: boolean
  error: Error | null
} = { data: undefined, isLoading: false, error: null }

vi.mock('@/hooks/useProductList', () => ({
  useProductList: () => mockProductListReturn,
}))

// ─── Sample data ───────────────────────────────────────────────────────────────

const PRODUCTS: Product[] = [
  {
    id: 1, product_id: 'PROD-001', name: 'Alpha Widget',
    manufacturer_address: '0xabc', registered_at: '', block_number: 1, tx_hash: '0x1',
  },
  {
    id: 2, product_id: 'PROD-002', name: 'Beta Gadget',
    manufacturer_address: '0xdef', registered_at: '', block_number: 2, tx_hash: '0x2',
  },
  {
    id: 3, product_id: 'ITEM-099', name: 'Gamma Prod',
    manufacturer_address: '0xghi', registered_at: '', block_number: 3, tx_hash: '0x3',
  },
]

// ─── Helpers ───────────────────────────────────────────────────────────────────

function setProducts(products: Product[] = PRODUCTS) {
  mockProductListReturn.data = { items: products, total: products.length }
  mockProductListReturn.isLoading = false
  mockProductListReturn.error = null
}

function setLoading() {
  mockProductListReturn.data = undefined
  mockProductListReturn.isLoading = true
  mockProductListReturn.error = null
}

function setError() {
  mockProductListReturn.data = undefined
  mockProductListReturn.isLoading = false
  mockProductListReturn.error = new Error('Network error')
}

// Wrapper so onChange → value prop roundtrip works correctly in unit tests
function StatefulCombobox(props: { disabled?: boolean; error?: string }) {
  const [value, setValue] = useState('')
  return <ProductCombobox value={value} onChange={setValue} {...props} />
}

// ─── Reset before each test ────────────────────────────────────────────────────

beforeEach(() => {
  mockProductListReturn.data = undefined
  mockProductListReturn.isLoading = false
  mockProductListReturn.error = null
})

// ─── filterProducts ────────────────────────────────────────────────────────────

describe('filterProducts', () => {
  it('returns products whose product_id starts with query (case-insensitive)', () => {
    const results = filterProducts(PRODUCTS, 'prod')
    const ids = results.map(p => p.product_id)
    expect(ids).toContain('PROD-001')
    expect(ids).toContain('PROD-002')
    expect(ids).not.toContain('ITEM-099')
  })

  it('returns products whose name contains query (substring, case-insensitive)', () => {
    const results = filterProducts(PRODUCTS, 'gamma')
    expect(results.map(p => p.product_id)).toContain('ITEM-099')
  })

  it('returns at most 8 results', () => {
    const many: Product[] = Array.from({ length: 20 }, (_, i) => ({
      id: i, product_id: `PROD-${i}`, name: `Product ${i}`,
      manufacturer_address: '0x0', registered_at: '', block_number: i, tx_hash: '0x0',
    }))
    expect(filterProducts(many, 'prod').length).toBeLessThanOrEqual(8)
  })

  it('returns empty array when query is empty string', () => {
    expect(filterProducts(PRODUCTS, '')).toHaveLength(0)
  })
})

// ─── ProductCombobox rendering ─────────────────────────────────────────────────

describe('ProductCombobox', () => {
  it('renders the input with correct placeholder', () => {
    setProducts()
    render(<StatefulCombobox />)
    expect(screen.getByPlaceholderText('e.g., PROD-8842')).toBeInTheDocument()
  })

  it('shows suggestions when user types a matching query', () => {
    setProducts()
    render(<StatefulCombobox />)
    fireEvent.change(screen.getByPlaceholderText('e.g., PROD-8842'), { target: { value: 'PROD' } })
    expect(screen.getByText('PROD-001')).toBeInTheDocument()
    expect(screen.getByText('PROD-002')).toBeInTheDocument()
  })

  it('hides suggestions when query is empty', () => {
    setProducts()
    render(<StatefulCombobox />)
    const input = screen.getByPlaceholderText('e.g., PROD-8842')
    fireEvent.change(input, { target: { value: 'PROD' } })
    fireEvent.change(input, { target: { value: '' } })
    expect(screen.queryByText('PROD-001')).not.toBeInTheDocument()
  })

  it('sets value to product_id when a suggestion is clicked', () => {
    setProducts()
    render(<StatefulCombobox />)
    fireEvent.change(screen.getByPlaceholderText('e.g., PROD-8842'), { target: { value: 'PROD' } })
    fireEvent.mouseDown(screen.getByText('PROD-001'))
    fireEvent.click(screen.getByText('PROD-001'))
    expect(screen.getByPlaceholderText('e.g., PROD-8842')).toHaveValue('PROD-001')
  })

  it('supports keyboard selection and Escape without submitting the form', () => {
    setProducts()
    render(<StatefulCombobox />)
    const input = screen.getByRole('combobox', { name: 'Product ID' })
    fireEvent.change(input, { target: { value: 'PROD' } })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(screen.getByRole('option', { name: 'PROD-001' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(input).toHaveValue('PROD-002')
    expect(input).toHaveAttribute('aria-expanded', 'false')
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input).toHaveAttribute('aria-expanded', 'true')
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(input).toHaveAttribute('aria-expanded', 'false')
  })

  it('closes dropdown when clicking outside', () => {
    setProducts()
    render(<StatefulCombobox />)
    fireEvent.change(screen.getByPlaceholderText('e.g., PROD-8842'), { target: { value: 'PROD' } })
    expect(screen.getByText('PROD-001')).toBeInTheDocument()
    fireEvent.mouseDown(document.body)
    expect(screen.queryByText('PROD-001')).not.toBeInTheDocument()
  })

  it('disables the input when disabled prop is true', () => {
    setProducts()
    render(<StatefulCombobox disabled={true} />)
    expect(screen.getByPlaceholderText('e.g., PROD-8842')).toBeDisabled()
  })

  it('shows no suggestions while loading', () => {
    setLoading()
    render(<StatefulCombobox />)
    fireEvent.change(screen.getByPlaceholderText('e.g., PROD-8842'), { target: { value: 'PROD' } })
    expect(screen.queryByText('PROD-001')).not.toBeInTheDocument()
  })

  it('renders input and shows no suggestions on fetch error', () => {
    setError()
    render(<StatefulCombobox />)
    fireEvent.change(screen.getByPlaceholderText('e.g., PROD-8842'), { target: { value: 'PROD' } })
    expect(screen.getByPlaceholderText('e.g., PROD-8842')).toBeInTheDocument()
    expect(screen.queryByText('PROD-001')).not.toBeInTheDocument()
  })
})
