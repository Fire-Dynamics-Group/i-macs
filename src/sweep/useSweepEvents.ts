/**
 * Hook that orchestrates a batch dashboard's data flow:
 *   1. backfill via GET /api/runs?batch_id=:id (existing rows on mount/refresh)
 *   2. open an EventSource on /api/sweeps/events
 *   3. on each run_completed event for THIS batch, append to runs + update counts
 *   4. on batch_done for this batch, close the stream and freeze in 'closed'
 *
 * Events for other batches are ignored — the SSE stream is global. On any
 * EventSource error the hook drops to 'error' status; the user can refresh.
 */
import { useEffect, useRef, useState } from "react";

import { getEventsUrl, listRuns, type Run } from "../api/client";

export type SweepStatus = "loading" | "streaming" | "closed" | "error";

export interface SweepEventsState {
  runs: Run[];
  status: SweepStatus;
  error: string | null;
  total: number | null;
  completed: number;
  errors: number;
}

interface RunCompletedPayload {
  type: "run_completed";
  run: Run;
  batch_id: string;
  total: number;
  completed: number;
  errors: number;
}

interface BatchDonePayload {
  type: "batch_done";
  batch_id: string;
  total: number;
  completed: number;
  errors: number;
}

export function useSweepEvents(batchId: string): SweepEventsState {
  const [runs, setRuns] = useState<Run[]>([]);
  const [status, setStatus] = useState<SweepStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [completed, setCompleted] = useState(0);
  const [errors, setErrors] = useState(0);

  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setError(null);

    (async () => {
      let backfill: Run[] = [];
      try {
        const data = await listRuns({ batchId });
        backfill = data.runs;
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setStatus("error");
        return;
      }
      if (cancelled) return;

      setRuns(backfill);
      setCompleted(backfill.length);
      setErrors(backfill.filter((r) => r.error).length);

      let url: string;
      try {
        url = await getEventsUrl();
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setStatus("error");
        return;
      }
      if (cancelled) return;

      const es = new EventSource(url);
      esRef.current = es;
      setStatus("streaming");

      es.addEventListener("run_completed", (ev) => {
        let payload: RunCompletedPayload;
        try {
          payload = JSON.parse((ev as MessageEvent).data) as RunCompletedPayload;
        } catch {
          return;
        }
        if (payload.batch_id !== batchId) return;
        setRuns((prev) => [...prev, payload.run]);
        setTotal(payload.total);
        setCompleted(payload.completed);
        setErrors(payload.errors);
      });

      es.addEventListener("batch_done", (ev) => {
        let payload: BatchDonePayload;
        try {
          payload = JSON.parse((ev as MessageEvent).data) as BatchDonePayload;
        } catch {
          return;
        }
        if (payload.batch_id !== batchId) return;
        setTotal(payload.total);
        setCompleted(payload.completed);
        setErrors(payload.errors);
        es.close();
        setStatus("closed");
      });

      es.onerror = () => {
        setStatus("error");
      };
    })();

    return () => {
      cancelled = true;
      esRef.current?.close();
      esRef.current = null;
    };
  }, [batchId]);

  return { runs, status, error, total, completed, errors };
}
