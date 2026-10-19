import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/utils/cn";
import { X } from "lucide-react";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  className?: string;
}

export default function Modal({
  open,
  onClose,
  title,
  children,
  className,
}: ModalProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open || !panelRef.current) return;
    const panel = panelRef.current;
    const overlay = panel.parentElement!;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    const siblings = Array.from(document.body.children).filter(
      (el) => el !== overlay,
    ) as HTMLElement[];
    const inertBefore = siblings.map((el) => el.inert);
    siblings.forEach((el) => {
      el.inert = true;
    });
    document.body.style.overflow = "hidden";
    const focusable = () =>
      Array.from(
        panel.querySelectorAll<HTMLElement>(
          "button, a[href], input, select, textarea, [tabindex]",
        ),
      ).filter(
        (el) =>
          !el.hasAttribute("disabled") &&
          el.tabIndex >= 0 &&
          !el.closest("[hidden]") &&
          getComputedStyle(el).display !== "none",
      );
    (focusable()[0] ?? panel).focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeRef.current();
      }
      if (event.key === "Tab") {
        const items = focusable();
        const first = items[0] ?? panel;
        const last = items.at(-1) ?? panel;
        if (
          !items.length ||
          (event.shiftKey && document.activeElement === first)
        ) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    const containFocus = (event: FocusEvent) => {
      if (!panel.contains(event.target as Node))
        (focusable()[0] ?? panel).focus();
    };
    document.addEventListener("keydown", keydown, true);
    document.addEventListener("focusin", containFocus);
    return () => {
      document.removeEventListener("keydown", keydown, true);
      document.removeEventListener("focusin", containFocus);
      document.body.style.overflow = overflow;
      siblings.forEach((el, index) => {
        el.inert = inertBefore[index];
      });
      if (previous?.isConnected) previous.focus();
    };
  }, [open]);
  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-[fadeIn_200ms_ease-out]"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className={cn(
          "max-h-[calc(100dvh-2rem)] overflow-y-auto overscroll-contain w-full max-w-lg rounded-card border border-border bg-surface p-6 shadow-card animate-[modalEnter_250ms_cubic-bezier(0.23,1,0.32,1)]",
          className,
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 id={titleId} className="text-lg font-semibold text-text">
            {title}
          </h2>
          <button
            onClick={onClose}
            className="rounded-button p-1 text-muted transition-colors hover:bg-surface2 hover:text-text"
            aria-label="Close modal"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
