import { createContext, useContext, useEffect, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

/**
 * The element a sheet mounts into: the device frame, not the scrolling page.
 * `.sheet` is absolutely positioned, so mounting it inside the scroll
 * container would park it at the bottom of the content instead of the screen.
 */
export const SheetHostContext = createContext<RefObject<HTMLDivElement | null> | null>(null);

type SheetProps = {
  label: string;
  onClose: () => void;
  children: ReactNode;
};

/** A bottom sheet over the device frame. Escape and the scrim both dismiss it. */
export function Sheet({ label, onClose, children }: SheetProps) {
  const host = useContext(SheetHostContext);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const sheet = (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="sheet" role="dialog" aria-modal="true" aria-label={label}>
        {children}
      </div>
    </>
  );

  return host?.current ? createPortal(sheet, host.current) : sheet;
}
