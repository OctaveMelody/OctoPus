interface Window {
  __TAURI__?: {
    core: {
      invoke<T>(command: string, args?: Record<string, unknown>): Promise<T>;
      convertFileSrc(filePath: string): string;
    };
    window: {
      getCurrentWindow(): {
        onCloseRequested(handler: (event: { preventDefault(): void }) => void): Promise<() => void>;
        onDragDropEvent(handler: (event: {
          payload: { type: "enter" | "over" | "drop" | "leave", paths?: string[] };
        }) => void): Promise<() => void>;
        close(): Promise<void>;
        destroy(): Promise<void>;
      };
    };
  };
}
