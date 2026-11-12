import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getUploadCanvasSummary,
  getUploadCanvasConfig,
  putUploadCanvasConfig,
  createUploadCanvasHandoff,
  searchUploadCanvasProjects,
  linkUploadCanvasProject,
  unlinkUploadCanvasProject,
  pushUploadCanvasRun,
  type UploadCanvasConfigUpdate,
  type UploadCanvasProject,
} from "../api/client";

export const UPLOAD_CANVAS_PRODUCTION_BACKEND =
  "https://backendfornextapp-production.up.railway.app";
export const UPLOAD_CANVAS_PRODUCTION_WEB = "https://upload-canvas.vercel.app";
export const UPLOAD_CANVAS_KEY_MESSAGE =
  "Upload Canvas key missing or invalid — open settings";

/** Map a failed project search onto the message the list should show. */
export function uploadCanvasSearchMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error ?? "");
  const lower = message.toLowerCase();
  if (
    /\b401\b/.test(message) ||
    /\b403\b/.test(message) ||
    /not configured/.test(lower) ||
    /app key/.test(lower) ||
    /imacs_app_key/.test(lower)
  ) {
    return UPLOAD_CANVAS_KEY_MESSAGE;
  }
  if (/\b404\b/.test(message) || /not found/.test(lower)) {
    return "Upload Canvas project search failed (not found).";
  }
  if (
    /failed to fetch/.test(lower) ||
    /network/.test(lower) ||
    /unreachable/.test(lower) ||
    /\b502\b/.test(message) ||
    /econnrefused/.test(lower)
  ) {
    return "Upload Canvas backend is unreachable.";
  }
  if (/\b503\b/.test(message)) {
    return "Upload Canvas backend is unreachable.";
  }
  return message || "Upload Canvas project search failed.";
}

interface UploadCanvasPanelProps {
  jobId: string;
}

/** How often to re-read the summary while a New project handoff is still unclaimed. */
const CLAIM_POLL_MS = 400;

async function safeOpenUrl(url: string) {
  // 1. Try Tauri invoke command open_external_url (native host OS opener)
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("open_external_url", { url });
    return;
  } catch (err) {
    console.warn("Tauri invoke open_external_url failed:", err);
  }

  // 2. Try Tauri plugin-opener
  try {
    const opener = await import("@tauri-apps/plugin-opener");
    if (opener?.openUrl) {
      await opener.openUrl(url);
      return;
    }
  } catch (err) {
    console.warn("Tauri plugin-opener openUrl failed:", err);
  }

  // 3. Fallback to window.open
  if (typeof window !== "undefined") {
    window.open(url, "_blank");
  }
}

export function UploadCanvasPanel({ jobId }: UploadCanvasPanelProps) {
  const queryClient = useQueryClient();
  const [showChooser, setShowChooser] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [openedUrl, setOpenedUrl] = useState<string | null>(null);
  const [awaitingClaim, setAwaitingClaim] = useState(false);
  const [appKey, setAppKey] = useState("");
  const [backendUrl, setBackendUrl] = useState(UPLOAD_CANVAS_PRODUCTION_BACKEND);
  const [webUrl, setWebUrl] = useState(UPLOAD_CANVAS_PRODUCTION_WEB);
  const [urlsFromConfig, setUrlsFromConfig] = useState(false);
  const [keyJustSaved, setKeyJustSaved] = useState(false);
  const [settingsNote, setSettingsNote] = useState<string | null>(null);

  const summaryQuery = useQuery({
    queryKey: ["upload-canvas-summary", jobId],
    queryFn: () => getUploadCanvasSummary(jobId),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      if (!awaitingClaim) return false;
      const projectId = query.state.data?.summary?.project_id;
      return projectId ? false : CLAIM_POLL_MS;
    },
  });

  const configQuery = useQuery({
    queryKey: ["upload-canvas-config"],
    queryFn: () => getUploadCanvasConfig(),
  });

  const hasAppKey = Boolean(configQuery.data?.has_app_key) || keyJustSaved;
  const keyMissing = configQuery.isSuccess && !hasAppKey;

  useEffect(() => {
    if (!configQuery.data || urlsFromConfig) return;
    setBackendUrl(configQuery.data.backend_base_url || UPLOAD_CANVAS_PRODUCTION_BACKEND);
    setWebUrl(configQuery.data.upload_canvas_base_url || UPLOAD_CANVAS_PRODUCTION_WEB);
    setUrlsFromConfig(true);
  }, [configQuery.data, urlsFromConfig]);

  const searchProjectsQuery = useQuery({
    queryKey: ["upload-canvas-projects", searchQuery],
    queryFn: () => searchUploadCanvasProjects(searchQuery),
    enabled: showChooser && hasAppKey,
  });

  const saveConfig = useMutation({
    mutationFn: (body: UploadCanvasConfigUpdate) => putUploadCanvasConfig(body),
    onSuccess: (_data, variables) => {
      if (variables.imacs_app_key) setKeyJustSaved(true);
      setAppKey("");
      setSettingsNote("Settings saved.");
      setErrorMessage(null);
      queryClient.invalidateQueries({ queryKey: ["upload-canvas-config"] });
      queryClient.invalidateQueries({ queryKey: ["upload-canvas-projects"] });
    },
    onError: (err: Error) => {
      setSettingsNote(err.message || "Could not save settings");
    },
  });

  const handoffMutation = useMutation({
    mutationFn: () => createUploadCanvasHandoff(jobId),
    onSuccess: async (data) => {
      setShowChooser(false);
      setErrorMessage(null);
      // The browser claims the handoff after this response. A null summary
      // until then is waiting, not a failure.
      setAwaitingClaim(true);
      if (data?.url) {
        setOpenedUrl(data.url);
        await safeOpenUrl(data.url);
      }
      queryClient.invalidateQueries({ queryKey: ["upload-canvas-summary", jobId] });
    },
    onError: (err: Error) => {
      const message = uploadCanvasSearchMessage(err);
      setErrorMessage(message);
      if (message === UPLOAD_CANVAS_KEY_MESSAGE) setShowSettings(true);
    },
  });

  const linkMutation = useMutation({
    mutationFn: (projectId: string) => linkUploadCanvasProject(jobId, projectId),
    onSuccess: async (data) => {
      setShowChooser(false);
      setErrorMessage(null);
      if (data?.url) {
        setOpenedUrl(data.url);
        await safeOpenUrl(data.url);
      }
      queryClient.invalidateQueries({ queryKey: ["upload-canvas-summary", jobId] });
    },
    onError: (err: Error) => {
      setErrorMessage(err.message || "Failed to link project");
    },
  });

  const pushMutation = useMutation({
    mutationFn: () => pushUploadCanvasRun(jobId),
    onSuccess: async (data) => {
      setErrorMessage(null);
      if (data?.url) {
        setOpenedUrl(data.url);
        await safeOpenUrl(data.url);
      }
      queryClient.invalidateQueries({ queryKey: ["upload-canvas-summary", jobId] });
    },
    onError: (err: Error) => {
      setErrorMessage(err.message || "Failed to push run to project");
    },
  });

  const unlinkMutation = useMutation({
    mutationFn: () => unlinkUploadCanvasProject(jobId),
    onSuccess: () => {
      setErrorMessage(null);
      queryClient.invalidateQueries({ queryKey: ["upload-canvas-summary", jobId] });
    },
    onError: (err: Error) => {
      setErrorMessage(err.message || "Failed to unlink project");
    },
  });

  const summary = summaryQuery.data?.summary;
  const isLinked = Boolean(summary?.project_id);

  useEffect(() => {
    if (isLinked) setAwaitingClaim(false);
  }, [isLinked]);

  const formatOutcome = (outcome: Record<string, unknown> | null) => {
    if (!outcome) return "No time-eq run yet";
    if (typeof outcome.reliabilityPercent === "number") {
      const fr = outcome.frPeriod
        ? ` (FR ${outcome.frPeriod} min)`
        : outcome.unprotected
          ? " (unprotected)"
          : "";
      return `${outcome.reliabilityPercent}% reliability${fr}`;
    }
    if (typeof outcome.reliability === "number") {
      const pct = Math.round(outcome.reliability * 100);
      const fr = outcome.frPeriod
        ? ` (FR ${outcome.frPeriod} min)`
        : outcome.unprotected
          ? " (unprotected)"
          : "";
      return `${pct}% reliability${fr}`;
    }
    if (outcome.teq !== undefined) {
      return `${outcome.teq} min`;
    }
    const status =
      outcome.status ||
      (outcome.overall_pass ? "Pass" : outcome.overall_pass === false ? "Fail" : null);
    if (status) return String(status);
    return "Completed";
  };

  return (
    <div className="mt-4 rounded-md border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Upload Canvas Link
        </h2>
        {isLinked && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setShowChooser(true)}
              className="text-xs text-blue-600 hover:underline"
            >
              Relink
            </button>
            <span className="text-xs text-slate-300">|</span>
            <button
              type="button"
              onClick={() => {
                if (window.confirm("Unlink this job from the Upload Canvas project?")) {
                  unlinkMutation.mutate();
                }
              }}
              className="text-xs text-rose-600 hover:underline"
            >
              Unlink
            </button>
          </div>
        )}
      </div>

      {errorMessage && (
        <div className="mt-2 rounded bg-rose-50 p-2 text-xs text-rose-700 border border-rose-200 flex justify-between items-center">
          <span>{errorMessage}</span>
          <button type="button" onClick={() => setErrorMessage(null)} className="font-bold ml-2">
            ×
          </button>
        </div>
      )}

      {openedUrl && (
        <div className="mt-3 rounded border border-blue-200 bg-blue-50 p-3 text-xs text-blue-900 flex items-center justify-between">
          <div className="flex-1 mr-2">
            <span className="font-semibold">Opened in browser:</span>{" "}
            <a
              href={openedUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={async (e) => {
                e.preventDefault();
                await safeOpenUrl(openedUrl);
              }}
              className="text-blue-700 underline font-medium hover:text-blue-900 break-all"
            >
              {openedUrl}
            </a>
          </div>
          <button
            type="button"
            onClick={() => {
              if (navigator.clipboard) {
                navigator.clipboard.writeText(openedUrl);
              }
            }}
            className="rounded bg-white px-2 py-1 text-xs border border-blue-300 text-blue-800 hover:bg-blue-100 whitespace-nowrap"
          >
            Copy link
          </button>
        </div>
      )}

      {summaryQuery.isError ? (
        <p className="mt-3 text-sm text-rose-700" role="alert">
          {(summaryQuery.error as Error).message}
        </p>
      ) : isLinked ? (
        <div className="mt-3">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-xs text-slate-500">Linked Project</p>
              <p className="font-medium text-slate-800">{summary?.project_name}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Last Sent</p>
              <p className="text-slate-700">
                {summary?.last_sent_at
                  ? new Date(summary.last_sent_at).toLocaleString()
                  : "Never"}
              </p>
            </div>
            <div className="col-span-2">
              <p className="text-xs text-slate-500">Latest Time-Eq Outcome</p>
              <p className="text-slate-700">{formatOutcome(summary?.outcome ?? null)}</p>
            </div>
          </div>

          <div className="mt-3">
            <button
              type="button"
              onClick={() => pushMutation.mutate()}
              disabled={pushMutation.isPending}
              className="inline-flex items-center rounded bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {pushMutation.isPending ? "Pushing latest run…" : "Open project"}
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-3">
          <p className="text-xs text-slate-500 mb-2">
            Link this MACs job to an upload-canvas time-equivalence project to view full run history from any device.
          </p>
          <button
            type="button"
            onClick={() => setShowChooser(true)}
            className="inline-flex items-center rounded bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            Open in Upload Canvas
          </button>
        </div>
      )}

      {/* Chooser Modal */}
      {showChooser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-6 shadow-xl text-slate-800">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="text-lg font-semibold">Open in Upload Canvas</h3>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setShowSettings((open) => !open)}
                  className="text-xs font-medium text-blue-700 hover:underline"
                >
                  Settings
                </button>
                <button
                  type="button"
                  onClick={() => setShowChooser(false)}
                  className="text-slate-400 hover:text-slate-600"
                >
                  ✕
                </button>
              </div>
            </div>

            {(showSettings || keyMissing) && (
              <form
                className="mt-4 rounded border border-slate-200 p-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  const typed = appKey.trim();
                  const body: UploadCanvasConfigUpdate = {
                    backend_base_url: backendUrl.trim(),
                    upload_canvas_base_url: webUrl.trim(),
                  };
                  if (typed) body.imacs_app_key = typed;
                  saveConfig.mutate(body);
                }}
              >
                <h4 className="font-medium text-sm text-slate-900">Upload Canvas settings</h4>
                <label htmlFor="imacs-app-key" className="mt-2 block text-xs text-slate-600">
                  i-macs app key
                </label>
                <input
                  id="imacs-app-key"
                  type="password"
                  name="imacs-app-key"
                  autoComplete="off"
                  spellCheck={false}
                  value={appKey}
                  onChange={(event) => setAppKey(event.target.value)}
                  placeholder={
                    hasAppKey
                      ? "Key saved — paste a new key to replace it"
                      : "Paste the i-macs app key"
                  }
                  className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-xs"
                />
                <p className="mt-1 text-xs text-slate-500">
                  Stored only on this computer. The saved key is not shown again.
                </p>
                <label htmlFor="uc-backend-url" className="mt-2 block text-xs text-slate-600">
                  Backend URL
                </label>
                <input
                  id="uc-backend-url"
                  type="url"
                  value={backendUrl}
                  onChange={(event) => setBackendUrl(event.target.value)}
                  className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-xs"
                />
                <label htmlFor="uc-web-url" className="mt-2 block text-xs text-slate-600">
                  Upload Canvas web URL
                </label>
                <input
                  id="uc-web-url"
                  type="url"
                  value={webUrl}
                  onChange={(event) => setWebUrl(event.target.value)}
                  className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-xs"
                />
                <div className="mt-2 flex items-center justify-between gap-2">
                  <button
                    type="submit"
                    disabled={saveConfig.isPending}
                    className="rounded bg-slate-800 px-3 py-1 text-xs font-medium text-white hover:bg-slate-900 disabled:opacity-50"
                  >
                    {saveConfig.isPending ? "Saving…" : "Save settings"}
                  </button>
                  {settingsNote && (
                    <p className="text-xs text-slate-600">{settingsNote}</p>
                  )}
                </div>
              </form>
            )}

            <div className="mt-4 flex flex-col gap-4">
              <div className="rounded border border-slate-200 p-3 hover:border-blue-400">
                <h4 className="font-medium text-sm text-slate-900">New project</h4>
                <p className="text-xs text-slate-500 mt-1">
                  Create a new time-equivalence project pre-filled with this job's critical temperature, section, and section factor.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    if (keyMissing) {
                      setShowSettings(true);
                      setErrorMessage(UPLOAD_CANVAS_KEY_MESSAGE);
                      return;
                    }
                    handoffMutation.mutate();
                  }}
                  disabled={handoffMutation.isPending}
                  className="mt-2 rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {handoffMutation.isPending ? "Creating handoff…" : "Create new project"}
                </button>
              </div>

              <div className="rounded border border-slate-200 p-3">
                <h4 className="font-medium text-sm text-slate-900">Link to existing project</h4>
                <p className="text-xs text-slate-500 mt-1">
                  Search and link to an existing time-eq project in Upload Canvas.
                </p>

                <div className="mt-2 flex gap-2">
                  <input
                    type="text"
                    placeholder="Search projects..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
                  />
                </div>

                <div className="mt-2 max-h-40 overflow-y-auto divide-y divide-slate-100">
                  {searchProjectsQuery.isLoading && (
                    <p className="p-2 text-xs text-slate-500">Searching…</p>
                  )}
                  {keyMissing && (
                    <p role="alert" className="p-2 text-xs text-rose-700">
                      {UPLOAD_CANVAS_KEY_MESSAGE}
                    </p>
                  )}
                  {searchProjectsQuery.isError && (
                    <p role="alert" className="p-2 text-xs text-rose-700">
                      {uploadCanvasSearchMessage(searchProjectsQuery.error)}
                    </p>
                  )}
                  {searchProjectsQuery.data?.projects?.map((proj: UploadCanvasProject) => (
                    <div
                      key={proj.id}
                      className="flex items-center justify-between p-2 hover:bg-slate-50"
                    >
                      <span className="text-xs font-medium text-slate-800 truncate mr-2">
                        {proj.name}
                      </span>
                      <button
                        type="button"
                        onClick={() => linkMutation.mutate(proj.id)}
                        disabled={linkMutation.isPending}
                        className="rounded border border-slate-300 px-2 py-0.5 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                      >
                        Link & Open
                      </button>
                    </div>
                  ))}
                  {!searchProjectsQuery.isError &&
                    !keyMissing &&
                    searchProjectsQuery.data?.projects?.length === 0 && (
                    <p className="p-2 text-xs text-slate-400">No time-eq projects found.</p>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-4 flex justify-end border-t pt-3">
              <button
                type="button"
                onClick={() => setShowChooser(false)}
                className="rounded border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
