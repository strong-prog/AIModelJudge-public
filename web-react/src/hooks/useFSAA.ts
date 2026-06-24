/** File System Access API — browser-based fallback for Dev Mode without agent.
 * Only works in Chrome/Edge (chromium-based browsers with showDirectoryPicker).
 */
import { useCallback, useState } from "react";

type FSHandle = FileSystemDirectoryHandle;

export interface FSAAState {
  /** Whether the browser supports FSAA */
  supported: boolean;
  /** Currently selected directory name, or null */
  dirName: string | null;
  /** The active directory handle */
  handle: FSHandle | null;
  /** Whether we're currently selecting a directory */
  selecting: boolean;
  /** Last error message */
  error: string | null;
}

// Check support eagerly
function isFSAASupported(): boolean {
  try {
    return typeof window !== "undefined" && "showDirectoryPicker" in window;
  } catch {
    return false;
  }
}

export function useFSAA() {
  const [state, setState] = useState<FSAAState>({
    supported: isFSAASupported(),
    dirName: null,
    handle: null,
    selecting: false,
    error: null,
  });

  const selectDirectory = useCallback(async () => {
    if (!state.supported) {
      setState((s) => ({ ...s, error: "FSAA не поддерживается в этом браузере. Используйте Chrome или Edge." }));
      return;
    }
    setState((s) => ({ ...s, selecting: true, error: null }));
    try {
      const handle = await (window as any).showDirectoryPicker({ mode: "readwrite" });
      setState((s) => ({ ...s, handle, dirName: handle.name, selecting: false }));
    } catch (err: any) {
      if (err?.name === "AbortError") {
        setState((s) => ({ ...s, selecting: false }));
      } else {
        setState((s) => ({ ...s, selecting: false, error: err?.message || "Ошибка выбора папки" }));
      }
    }
  }, [state.supported]);

  const readFile = useCallback(async (path: string): Promise<string> => {
    const handle = state.handle;
    if (!handle) throw new Error("No directory selected");
    const parts = path.split("/").filter(Boolean);
    let current: FileSystemDirectoryHandle | FileSystemFileHandle = handle;
    for (const part of parts) {
      if (current.kind === "directory") {
        current = await current.getFileHandle(part);
      } else {
        throw new Error(`Cannot navigate into file: ${part}`);
      }
    }
    const file = await (current as FileSystemFileHandle).getFile();
    return await file.text();
  }, [state.handle]);

  const writeFile = useCallback(async (path: string, content: string): Promise<void> => {
    const handle = state.handle;
    if (!handle) throw new Error("No directory selected");
    const parts = path.split("/").filter(Boolean);
    if (parts.length === 0) throw new Error("Empty path");
    const fileName = parts.pop()!;
    let dir: FileSystemDirectoryHandle = handle;
    for (const part of parts) {
      dir = await dir.getDirectoryHandle(part, { create: true });
    }
    const fileHandle = await dir.getFileHandle(fileName, { create: true });
    const writable = await fileHandle.createWritable();
    await writable.write(content);
    await writable.close();
  }, [state.handle]);

  const listDir = useCallback(async (path: string = "."): Promise<string[]> => {
    const handle = state.handle;
    if (!handle) throw new Error("No directory selected");
    let dir: FileSystemDirectoryHandle = handle;
    if (path !== ".") {
      const parts = path.split("/").filter(Boolean);
      for (const part of parts) {
        dir = await dir.getDirectoryHandle(part);
      }
    }
    const entries: string[] = [];
    // FileSystemDirectoryHandle entries() async iterator — cast to work around TS DOM types
    for await (const [name] of (dir as any).entries()) {
      entries.push(name as string);
    }
    return entries.sort();
  }, [state.handle]);

  const release = useCallback(() => {
    setState((s) => ({ ...s, handle: null, dirName: null }));
  }, []);

  return {
    state,
    selectDirectory,
    readFile,
    writeFile,
    listDir,
    release,
  };
}
