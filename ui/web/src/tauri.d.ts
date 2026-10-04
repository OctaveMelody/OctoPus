interface Window {
  __TAURI__?: {
    core: {
      invoke<T>(command: string, args?: Record<string, unknown>): Promise<T>;
      convertFileSrc(filePath: string): string;
    };
    event?: { listen(name: string, handler: (event: {payload: unknown}) => void): Promise<() => void>; };
    window: {
      getCurrentWindow(): {
        onCloseRequested(handler: (event: { preventDefault(): void }) => void): Promise<() => void>;
        onDragDropEvent(handler: (event: {
          payload: { type: "enter" | "over" | "drop" | "leave", paths?: string[], position?: { x: number; y: number } };
        }) => void): Promise<() => void>;
        close(): Promise<void>;
        destroy(): Promise<void>;
      };
    };
  };
}
