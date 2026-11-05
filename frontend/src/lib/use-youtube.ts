import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { csrf, type Media } from "./storage";
export type YouTubeJob = {
  id?: string;
  status:
    | "idle"
    | "checking"
    | "downloading"
    | "processing"
    | "ready"
    | "cancelled"
    | "error";
  progress?: number | null;
  title?: string;
  message?: string;
  media?: Media;
};
export function isYouTube(url: string) {
  try {
    return /^(www\.|m\.|music\.)?(youtube\.com|youtu\.be)$/.test(
      new URL(url).hostname,
    );
  } catch {
    return false;
  }
}
export function useYouTube() {
  const [job, setJob] = useState<YouTubeJob>({ status: "idle" });
  const [starting, setStarting] = useState(false);
  const initiated = useRef<string | undefined>(undefined);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    const controller = new AbortController();
    let fetching = false;
    async function refresh() {
      if (fetching) return;
      fetching = true;
      try {
        const response = await fetch("/api/youtube", {
          cache: "no-store",
          signal: controller.signal,
        });
        if (response.ok && active.current) setJob(await response.json());
      } catch {
        /* Preserve the latest progress while reconnecting. */
      } finally {
        fetching = false;
      }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 1000);
    return () => {
      active.current = false;
      controller.abort();
      clearInterval(timer);
    };
  }, []);
  async function start(url: string) {
    setStarting(true);
    try {
      await fetch("/api/youtube");
      const response = await fetch("/api/youtube", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ url }),
      });
      const result = await response.json();
      if (!response.ok)
        throw Error(result.error || "Não foi possível iniciar o download.");
      initiated.current = result.id;
      if (active.current) setJob(result);
      return true;
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Falha ao iniciar download.",
      );
      return false;
    } finally {
      if (active.current) setStarting(false);
    }
  }
  async function cancel() {
    try {
      const response = await fetch("/api/youtube", {
        method: "DELETE",
        headers: { "X-CSRFToken": csrf() },
      });
      if (!response.ok) throw Error();
      if (active.current) setJob(await response.json());
    } catch {
      toast.error("Não foi possível cancelar. Tente novamente.");
    }
  }
  return {
    job,
    start,
    cancel,
    initiated,
    starting,
    busy:
      starting ||
      ["checking", "downloading", "processing"].includes(job.status),
  };
}
