import { useEffect, useRef, useState, useId } from "react";
import type { Product } from "@/types";
import { useProductList } from "@/hooks/useProductList";
import { ownsRecord, hasCurrentIdentity } from "@/utils/permissions";

// ─── Pure utility ─────────────────────────────────────────────────────────────

export function filterProducts(products: Product[], query: string): Product[] {
  if (query === "") return [];
  const q = query.toLowerCase();
  return products
    .filter(
      (p) =>
        p.product_id.toLowerCase().startsWith(q) ||
        p.name.toLowerCase().startsWith(q),
    )
    .slice(0, 8);
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface ProductComboboxProps {
  id?: string;
  value: string;
  onChange: (val: string) => void;
  disabled?: boolean;
  error?: string;
  ownedOnly?: boolean;
  ownerAddress?: string | null;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function ProductCombobox({
  id,
  value,
  onChange,
  disabled,
  error,
  ownedOnly = false,
  ownerAddress,
}: ProductComboboxProps) {
  const { data, isLoading, error: fetchError } = useProductList();
  const products = (data?.items ?? []).filter(
    (product) =>
      !ownedOnly ||
      (ownsRecord(product, ownerAddress || null) &&
        hasCurrentIdentity(product) &&
        !product.has_shipment),
  );
  const suggestions = filterProducts(products, value);

  const [isOpen, setIsOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const generatedId = useId();
  const listId = `${generatedId}-suggestions`;
  const containerRef = useRef<HTMLDivElement>(null);

  // Close when value is cleared externally
  useEffect(() => {
    if (value === "") setIsOpen(false);
  }, [value]);

  // Close on outside click
  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, []);

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    setActive(-1);
    const newValue = e.target.value;
    onChange(newValue);
    if (
      !fetchError &&
      !isLoading &&
      products.length > 0 &&
      newValue.length > 0
    ) {
      setIsOpen(true);
    } else {
      setIsOpen(false);
    }
  }

  return (
    <div ref={containerRef} className="relative w-full">
      <input
        id={id}
        role="combobox"
        aria-label={id ? undefined : "Product ID"}
        aria-autocomplete="list"
        aria-expanded={isOpen && suggestions.length > 0}
        aria-controls={isOpen && suggestions.length > 0 ? listId : undefined}
        aria-activedescendant={
          isOpen && active >= 0 && active < suggestions.length
            ? `${listId}-${active}`
            : undefined
        }
        aria-invalid={!!error}
        onBlur={() => setIsOpen(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape" && isOpen) {
            event.preventDefault();
            event.stopPropagation();
            setIsOpen(false);
            setActive(-1);
          }
          if (
            (event.key === "ArrowDown" || event.key === "ArrowUp") &&
            suggestions.length
          ) {
            event.preventDefault();
            setIsOpen(true);
            setActive((index) =>
              event.key === "ArrowDown"
                ? (index + 1) % suggestions.length
                : index <= 0
                  ? suggestions.length - 1
                  : index - 1,
            );
          }
          if (
            event.key === "Enter" &&
            isOpen &&
            active >= 0 &&
            suggestions[active]
          ) {
            event.preventDefault();
            onChange(suggestions[active].product_id);
            setIsOpen(false);
            setActive(-1);
          }
        }}
        type="text"
        value={value}
        onChange={handleInputChange}
        placeholder="e.g., PROD-8842"
        disabled={disabled}
        className={[
          "w-full rounded-button border px-3 py-2 text-sm",
          "bg-surface text-text placeholder:text-muted",
          "border-border focus:border-accent focus:outline-hidden",
          "disabled:cursor-not-allowed disabled:opacity-50",
          error ? "border-red-500" : "",
        ].join(" ")}
      />

      {isOpen && suggestions.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          aria-label="Matching products"
          className="absolute z-50 mt-1 w-full rounded-button border border-border bg-surface shadow-card"
        >
          {suggestions.map((product, index) => (
            <li
              key={product.product_id}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={active === index}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onChange(product.product_id);
                setIsOpen(false);
                setActive(-1);
              }}
              className="cursor-pointer px-3 py-2 text-sm text-text hover:bg-surface2"
            >
              {product.product_id}
            </li>
          ))}
        </ul>
      )}

      {isOpen &&
        suggestions.length === 0 &&
        value.length > 0 &&
        !isLoading &&
        !fetchError && (
          <div className="absolute z-50 mt-1 w-full rounded-button border border-border bg-surface px-3 py-2 shadow-card">
            <p className="text-sm text-muted">
              No match for &quot;{value}&quot;
            </p>
          </div>
        )}

      {error && <p className="mt-1 text-xs text-red-500">{error}</p>}
    </div>
  );
}
