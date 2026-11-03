import { useCallback, useEffect, useRef, useState } from "react";
import { listJobs } from "../api/endpoints";
import type { JobStatusResponse } from "../types/api";

const ACTIVE = new Set(["pending", "processing"]);
const POLL_MS = 2000;
const FILENAME_KEY = "norvia.jobFilenames";

function loadFilenameMap(): Record<string, string> {
  try {
    const raw = sessionStorage.getItem(FILENAME_KEY);
    return raw ? (JSON.parse(raw) as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function saveFilenameMap(map: Record<string, string>): void {
  sessionStorage.setItem(FILENAME_KEY, JSON.stringify(map));
}

/** Merge API jobs with locally remembered filenames (pending jobs lack document.filename). */
function withLocalNames(jobs: JobStatusResponse[]): JobStatusResponse[] {
  const map = loadFilenameMap();
  return jobs.map((j) => {
    if (j.filename) {
      if (map[j.job_id] !== j.filename) {
        map[j.job_id] = j.filename;
        saveFilenameMap(map);
      }
      return j;
    }
    const local = map[j.job_id];
    return local ? { ...j, filename: local } : j;
  });
}

export function rememberJobFilename(jobId: string, filename: string): void {
  const map = loadFilenameMap();
  map[jobId] = filename;
  saveFilenameMap(map);
}

export function useJobPolling(enabled: boolean) {
  const [jobs, setJobs] = useState<JobStatusResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const timer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    try {
      const next = withLocalNames(await listJobs());
      setJobs(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs");
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      setJobs([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    void (async () => {
      await refresh();
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled, refresh]);

  useEffect(() => {
    if (!enabled) return;
    const hasActive = jobs.some((j) => ACTIVE.has(j.status));
    if (timer.current !== null) {
      window.clearInterval(timer.current);
      timer.current = null;
    }
    if (!hasActive) return;
    timer.current = window.setInterval(() => {
      void refresh();
    }, POLL_MS);
    return () => {
      if (timer.current !== null) {
        window.clearInterval(timer.current);
        timer.current = null;
      }
    };
  }, [enabled, jobs, refresh]);

  const upsertLocal = useCallback((job: JobStatusResponse) => {
    if (job.filename) rememberJobFilename(job.job_id, job.filename);
    setJobs((prev) => {
      const rest = prev.filter((j) => j.job_id !== job.job_id);
      return withLocalNames([job, ...rest]);
    });
  }, []);

  return { jobs, error, loading, refresh, upsertLocal };
}
