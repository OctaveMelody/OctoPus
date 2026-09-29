import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

type Props = {
  source: string;
  pageNumber: number;
  scale: number;
  label: string;
  errorLabel: string;
  active?: boolean;
  className?: string;
  style?: CSSProperties;
  lazy?: boolean;
  root?: Element | null;
  onRenderError?(message: string | null): void;
};

export function PdfPageCanvas({
  source,
  pageNumber,
  scale,
  label,
  errorLabel,
  active = true,
  className,
  style,
  lazy = false,
  root = null,
  onRenderError,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [nearViewport, setNearViewport] = useState(!lazy);
  const [renderError, setRenderError] = useState(false);

  useEffect(() => {
    if (!lazy) {
      setNearViewport(true);
      return;
    }
    setNearViewport(false);
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (!("IntersectionObserver" in window)) {
      setNearViewport(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setNearViewport(true);
          observer.disconnect();
        }
      },
      { root, rootMargin: "100px" },
    );
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [lazy, root]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!active || !canvas || !source || scale <= 0 || (lazy && !nearViewport)) return;
    const controller = new AbortController();
    setRenderError(false);
    onRenderError?.(null);
    const reportError = (error: unknown) => {
      if (!controller.signal.aborted) {
        setRenderError(true);
        onRenderError?.(error instanceof Error ? error.message : String(error));
      }
    };
    void import("./pdf-runtime")
      .then(({ renderPdfPage }) => controller.signal.aborted
        ? undefined
        : renderPdfPage(source, pageNumber, scale, canvas, controller.signal))
      .catch(reportError);
    return () => {
      controller.abort();
      canvas.width = 0;
      canvas.height = 0;
    };
  }, [active, lazy, nearViewport, onRenderError, pageNumber, scale, source]);

  return (
    <canvas
      aria-label={renderError ? `${label}. ${errorLabel}` : label}
      className={className}
      height={0}
      ref={canvasRef}
      role="img"
      style={style}
      title={renderError ? `${label}. ${errorLabel}` : label}
      width={0}
    />
  );
}
