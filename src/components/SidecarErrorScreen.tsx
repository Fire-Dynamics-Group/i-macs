import { Component, ReactNode } from "react";
import { invoke } from "@tauri-apps/api/core";

interface State {
  hasError: boolean;
  message: string;
  logDir: string | null;
}

interface Props {
  children: ReactNode;
}

/**
 * Catches errors from React Query's API client (sidecar unreachable, port
 * resolution failure, network blips after the sidecar has died) and shows
 * a recovery card instead of a blank webview.
 *
 * Slice 5 will broaden this to handle the explicit `sidecar-error` event
 * Tauri emits when /healthz never goes green.
 */
export class SidecarErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: "", logDir: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message, logDir: null };
  }

  async componentDidCatch() {
    try {
      const logDir = await invoke<string>("get_log_dir");
      this.setState({ logDir });
    } catch {
      // Tauri command not available (e.g. running in a plain browser test).
    }
  }

  async openLogFolder() {
    if (!this.state.logDir) return;
    try {
      const { revealItemInDir } = await import("@tauri-apps/plugin-opener");
      await revealItemInDir(this.state.logDir);
    } catch {
      // Plugin not loaded (test env); ignore.
    }
  }

  retry = () => {
    this.setState({ hasError: false, message: "", logDir: null });
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="mx-auto max-w-xl p-8">
        <div className="rounded-md border border-rose-200 bg-rose-50 p-6 shadow-sm">
          <h1 className="text-lg font-semibold text-rose-800">
            MACS+ Automation can't reach its background service
          </h1>
          <p className="mt-2 text-sm text-rose-900">{this.state.message}</p>
          {this.state.logDir && (
            <p className="mt-2 text-xs text-rose-700">
              Log directory: <code>{this.state.logDir}</code>
            </p>
          )}
          <div className="mt-4 flex gap-3">
            <button
              onClick={() => this.openLogFolder()}
              disabled={!this.state.logDir}
              className="rounded bg-rose-700 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              Open log folder
            </button>
            <button
              onClick={this.retry}
              className="rounded border border-rose-300 px-3 py-1.5 text-sm text-rose-800"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }
}
