import { useEffect, useRef, useState } from 'react'
import type { Product } from '@/types'
import { useProductList } from '@/hooks/useProductList'

// ─── Pure utility ─────────────────────────────────────────────────────────────

export function filterProducts(products: Product[], query: string): Product[] {
  if (query === '') return []
  const q = query.toLowerCase()
  return products
    .filter(
      p => p.product_id.toLowerCase().startsWith(q) || p.name.toLowerCase().startsWith(q)
    )
    .slice(0, 8)
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface ProductComboboxProps {
  value: string
  onChange: (val: string) => void
  disabled?: boolean
  error?: string
}

// ─── Component ────────────────────────────────────────────────────────────────

export function ProductCombobox({ value, onChange, disabled, error }: ProductComboboxProps) {
  const { data, isLoading, error: fetchError } = useProductList()
  const products = data?.items ?? []
  const suggestions = filterProducts(products, value)

  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Close when value is cleared externally
  useEffect(() => {
    if (value === '') setIsOpen(false)
  }, [value])

  // Close on outside click
  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [])

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const newValue = e.target.value
    onChange(newValue)
    if (!fetchError && !isLoading && products.length > 0 && newValue.length > 0) {
      setIsOpen(true)
    } else {
      setIsOpen(false)
    }
  }

  return (
    <div ref={containerRef} className="relative w-full">
      <input
        type="text"
        value={value}
        onChange={handleInputChange}
        placeholder="e.g., PROD-8842"
        disabled={disabled}
        className={[
          'w-full rounded-button border px-3 py-2 text-sm',
          'bg-surface text-text placeholder:text-muted',
          'border-border focus:border-accent focus:outline-hidden',
          'disabled:cursor-not-allowed disabled:opacity-50',
          error ? 'border-red-500' : '',
        ].join(' ')}
      />

      {isOpen && suggestions.length > 0 && (
        <ul className="absolute z-50 mt-1 w-full rounded-button border border-border bg-surface shadow-card">
          {suggestions.map(product => (
            <li
              key={product.product_id}
              onMouseDown={e => e.preventDefault()}
              onClick={() => {
                onChange(product.product_id)
                setIsOpen(false)
              }}
              className="cursor-pointer px-3 py-2 text-sm text-text hover:bg-surface2"
            >
              {product.product_id}
            </li>
          ))}
        </ul>
      )}

      {isOpen && suggestions.length === 0 && value.length > 0 && !isLoading && !fetchError && (
        <div className="absolute z-50 mt-1 w-full rounded-button border border-border bg-surface px-3 py-2 shadow-card">
          <p className="text-sm text-muted">No match for &quot;{value}&quot;</p>
        </div>
      )}

      {error && (
        <p className="mt-1 text-xs text-red-500">{error}</p>
      )}
    </div>
  )
}
