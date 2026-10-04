import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export type MenuAction = { label: string; title?: string; disabled?: boolean; run(): void };

/** Portal menus remain visible outside narrow, scrolling panel headings. */
export function ActionMenu({ label, title, actions }: {
  label: string; title?: string; actions: MenuAction[];
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const firstFromEnd = useRef(false);
  useLayoutEffect(() => {
    if (!open || !trigger.current || !menu.current) return;
    const rect = trigger.current.getBoundingClientRect();
    const width = menu.current.offsetWidth;
    const height = menu.current.offsetHeight;
    setPosition({
      left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
      top: rect.bottom + height + 4 <= window.innerHeight
        ? rect.bottom + 4 : Math.max(8, rect.top - height - 4),
    });
    const buttons = menu.current.querySelectorAll<HTMLButtonElement>("button:not(:disabled)");
    (buttons[firstFromEnd.current ? buttons.length - 1 : 0] ?? menu.current).focus();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      if (!menu.current?.contains(event.target as Node)
        && !trigger.current?.contains(event.target as Node)) setOpen(false);
    };
    const close = (event: Event) => {
      if (!(event.target instanceof Node) || !menu.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [open]);
  return <>
    <button ref={trigger} title={title} type="button" aria-haspopup="menu" aria-expanded={open}
      onClick={() => { firstFromEnd.current = false; setOpen(!open); }}
      onKeyDown={(event) => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          firstFromEnd.current = event.key === "ArrowUp";
          setOpen(true);
        }
      }}>{label} ▾</button>
    {open && createPortal(<div ref={menu} role="menu" tabIndex={-1} aria-label={label}
      className="panel-action-menu" style={position} onKeyDown={(event) => {
        const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(
          "button:not(:disabled)",
        ));
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        if (event.key === "Escape" || event.key === "Tab") {
          setOpen(false);
          trigger.current?.focus();
          if (event.key === "Escape") event.preventDefault();
        } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
            : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
          buttons[next]?.focus();
        }
      }}>
      {actions.map((action) => <button key={action.label} role="menuitem" type="button"
        title={action.title} disabled={action.disabled} onClick={() => {
          setOpen(false);
          trigger.current?.focus();
          action.run();
        }}>{action.label}</button>)}
    </div>, document.body)}
  </>;
}
