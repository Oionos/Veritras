import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";

/** Keep below-fold chart code out of startup; preserve its reserved layout. */
export default function DeferredSection({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!("IntersectionObserver" in window)) {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "100px" },
    );
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  const placeholder = (
    <div
      className="flex h-full items-center justify-center text-sm text-muted"
      role="status"
    >
      {label} loads when visible.
    </div>
  );
  return (
    <div ref={ref} className="h-full" aria-label={label}>
      {visible ? (
        <Suspense fallback={placeholder}>{children}</Suspense>
      ) : (
        placeholder
      )}
    </div>
  );
}
