import { useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import type { LayoutId } from "./types";

type Split = { x: number; y: number };
type Props = {
  layout: LayoutId;
  axis: "x" | "y";
  split: Split;
  label: string;
  onChange: (split: Split) => void;
};

/** Resize the two panes adjacent to this boundary, preserving the other boundary in T1. */
export function PanelDivider({ layout, axis, split, label, onChange }: Props) {
  const vertical = axis === "x" || layout === "T1";
  const drag = useRef<{ pointerId: number; coordinate: number; size: number; split: Split } | null>(null);
  const [dragging, setDragging] = useState(false);
  const maximum = layout === "T1"
    ? axis === "x" ? split.x + split.y - 20 : 80 - split.x
    : 80;

  function resize(value: number, initial: Split) {
    const max = layout === "T1"
      ? axis === "x" ? initial.x + initial.y - 20 : 80 - initial.x
      : 80;
    const bounded = Math.min(max, Math.max(20, value));
    const next = { ...initial, [axis]: bounded };
    if (layout === "T1" && axis === "x") next.y = initial.y + initial.x - bounded;
    onChange(next);
  }

  function start(event: PointerEvent<HTMLDivElement>) {
    if (!event.isPrimary || event.button !== 0) return;
    const workspace = event.currentTarget.parentElement!;
    const rect = workspace.getBoundingClientRect();
    drag.current = {
      pointerId: event.pointerId,
      coordinate: vertical ? event.clientX : event.clientY,
      size: Math.max(1, (vertical ? rect.width : rect.height) - (layout === "T1" ? 16 : 8)),
      split: { ...split },
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.focus();
    setDragging(true);
    event.preventDefault();
  }

  function move(event: PointerEvent<HTMLDivElement>) {
    const initial = drag.current;
    if (!initial || initial.pointerId !== event.pointerId) return;
    const coordinate = vertical ? event.clientX : event.clientY;
    resize(initial.split[axis] + (coordinate - initial.coordinate) / initial.size * 100, initial.split);
  }

  function finish(event: PointerEvent<HTMLDivElement>) {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function keyboard(event: KeyboardEvent<HTMLDivElement>) {
    const decrement = vertical ? "ArrowLeft" : "ArrowUp";
    const increment = vertical ? "ArrowRight" : "ArrowDown";
    let value: number;
    if (event.key === decrement) value = split[axis] - (event.shiftKey ? 10 : 1);
    else if (event.key === increment) value = split[axis] + (event.shiftKey ? 10 : 1);
    else if (event.key === "Home") value = 20;
    else if (event.key === "End") value = maximum;
    else return;
    event.preventDefault();
    resize(value, split);
  }

  return <div
    className={`panel-divider divider-${axis} ${vertical ? "vertical" : "horizontal"}${dragging ? " resizing" : ""}`}
    role="separator" tabIndex={0} aria-label={label}
    aria-orientation={vertical ? "vertical" : "horizontal"}
    aria-valuemin={20} aria-valuemax={maximum} aria-valuenow={Math.round(split[axis])}
    onPointerDown={start} onPointerMove={move} onPointerUp={finish}
    onPointerCancel={finish} onLostPointerCapture={finish} onKeyDown={keyboard}
  />;
}
