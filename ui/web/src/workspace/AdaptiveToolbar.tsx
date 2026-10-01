import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

/** Measure the full control row even while the compact alternative is visible. */
export function AdaptiveToolbar({ expanded, compact, label, className = "" }: {
  expanded: ReactNode; compact: ReactNode; label: string; className?: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const fullRow = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState(false);
  useLayoutEffect(() => {
    const slot = container.current;
    const row = fullRow.current;
    if (!slot || !row) return;
    const measure = () => {
      const narrow = row.getBoundingClientRect().width > slot.clientWidth + 1;
      if (narrow) row.querySelectorAll("details").forEach(details => { details.open = false; });
      setCollapsed(narrow);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(slot);
    observer.observe(row);
    measure();
    return () => observer.disconnect();
  }, []);
  return <div ref={container} className={`adaptive-toolbar ${className}`} role="toolbar"
    aria-label={label} data-compact={collapsed}>
    <div ref={fullRow} className="toolbar-expanded" aria-hidden={collapsed || undefined}
      inert={collapsed ? true : undefined}>{expanded}</div>
    {collapsed && <div className="toolbar-compact">{compact}</div>}
  </div>;
}
