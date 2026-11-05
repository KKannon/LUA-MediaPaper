import { useEffect } from "react";

/** Acquire only for a visible live display; release on navigation or unmount. */
export function useScreenWakeLock(enabled: boolean) {
  useEffect(() => {
    if (!enabled || !("wakeLock" in navigator)) return;
    let active = true,
      requesting = false;
    let sentinel: WakeLockSentinel | null = null;
    async function request() {
      if (
        !active ||
        requesting ||
        sentinel ||
        document.visibilityState !== "visible"
      )
        return;
      requesting = true;
      try {
        const lock = await navigator.wakeLock.request("screen");
        if (!active) {
          await lock.release();
          return;
        }
        sentinel = lock;
        lock.addEventListener("release", () => {
          if (sentinel === lock) sentinel = null;
        });
      } catch {
        /* HTTPS, browser support and power-saving policies control availability. */
      } finally {
        requesting = false;
      }
    }
    void request();
    const interval = setInterval(() => void request(), 15000);
    document.addEventListener("visibilitychange", request);
    document.addEventListener("pointerdown", request);
    return () => {
      active = false;
      clearInterval(interval);
      document.removeEventListener("visibilitychange", request);
      document.removeEventListener("pointerdown", request);
      void sentinel?.release().catch(() => {});
    };
  }, [enabled]);
}
