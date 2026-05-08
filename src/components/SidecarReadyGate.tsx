import { useEffect, useState, type ReactNode } from "react";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";

import { fetchHealth } from "../api/client";

type Status =
  | { kind: "starting" }
  | { kind: "ready" }
  | { kind: "failed"; message: string };

/**
 * Gates the routed app on the sidecar actually being reachable.
 *
 * The Tauri shell spawns the Python sidecar in setup() and emits
 * `sidecar-ready` once `/healthz` returns 200. Until then the React webview
 * was racing the sidecar's bind() — first fetch came back "Failed to fetch"
 * and the error boundary fired before the user ever saw the form.
 *
 * Two paths here, because Tauri events are easy to miss:
 *   1. Subscribe to `sidecar-ready`. If it fires, we're good.
 *   2. Poll `/healthz` directly with backoff. This wins if React mounted
 *      after the event already fired (the listener is registered too late).
 *
 * Whichever resolves first wins and we render the children.
 */
export function SidecarReadyGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>({ kind: "starting" });

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;

    const markReady = () => {
      if (!cancelled) setStatus({ kind: "ready" });
    };

    // 1. Subscribe to the Tauri-side ready signal.
    listen("sidecar-ready", markReady).then((u) => {
      if (cancelled) {
        u();
      } else {
        unlisten = u;
      }
    });

    // 2. Poll /healthz ourselves so a missed event doesn't keep us stuck.
    (async () => {
      const start = Date.now();
      const timeoutMs = 30_000;
      let delay = 200;
      while (!cancelled) {
        try {
          await fetchHealth();
          markReady();
          return;
        } catch (err) {
          if (Date.now() - start > timeoutMs) {
            const message = err instanceof Error ? err.message : String(err);
            if (!cancelled) {
              setStatus({ kind: "failed", message });
            }
            return;
          }
          await new Promise((resolve) => setTimeout(resolve, delay));
          delay = Math.min(delay * 1.5, 1500);
        }
      }
    })();

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  if (status.kind === "ready") return <>{children}</>;

  return (
    <div className="mx-auto flex h-full max-w-xl items-center justify-center p-8">
      <div className="w-full rounded-md border border-slate-200 bg-white p-6 text-center shadow-sm">
        {status.kind === "starting" ? (
          <>
            <div className="mx-auto h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-blue-600" />
            <p className="mt-3 text-sm text-slate-600">Starting MACS+ Automation…</p>
            <p className="mt-1 text-xs text-slate-400">
              First boot is slowest — the sidecar's onedir extraction can take
              a few seconds.
            </p>
          </>
        ) : (
          <>
            <p className="text-sm font-medium text-rose-700">
              Background service didn't start
            </p>
            <p className="mt-2 text-xs text-rose-900">{status.message}</p>
            <button
              onClick={() => openLogFolder()}
              className="mt-4 rounded border border-rose-300 px-3 py-1.5 text-xs text-rose-800 hover:bg-rose-50"
            >
              Open log folder
            </button>
          </>
        )}
      </div>
    </div>
  );
}

async function openLogFolder() {
  try {
    const logDir = await invoke<string>("get_log_dir");
    const { revealItemInDir } = await import("@tauri-apps/plugin-opener");
    await revealItemInDir(logDir);
  } catch {
    // best-effort
  }
}
