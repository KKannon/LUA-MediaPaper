import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  csrf,
  defaultPreferences,
  presets,
  type Media,
  type Preferences,
} from "./storage";

type State = { media: Media; preferences: Preferences; revision: number };
type Changes = {
  media?: Media;
  preferences?: Partial<Preferences>;
  initialRevision?: number;
};
const merge = (older: Changes, newer: Changes): Changes => ({
  ...older,
  ...newer,
  preferences: { ...older.preferences, ...newer.preferences },
});
function initial(): State {
  try {
    return {
      media:
        JSON.parse(localStorage.getItem("lua:media") || "null") || presets[0],
      preferences: {
        ...defaultPreferences,
        ...JSON.parse(localStorage.getItem("lua:preferences") || "{}"),
      },
      revision: -1,
    };
  } catch {
    return { media: presets[0], preferences: defaultPreferences, revision: -1 };
  }
}

/** Explicit edits publish partial changes; readers only follow the server. */
export function useWallpaper(readOnly: boolean) {
  const [state, setState] = useState<State>(initial);
  const current = useRef(state);
  const pending = useRef<Changes>({});
  const publish = useRef<() => void>(() => {});
  useEffect(() => {
    let active = true,
      ready = false,
      sending = false,
      polling = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    function adopt(incoming: State) {
      if (!active || incoming.revision < current.current.revision) return;
      const next = {
        ...incoming,
        media: pending.current.media || incoming.media,
        preferences: {
          ...defaultPreferences,
          ...incoming.preferences,
          ...pending.current.preferences,
        },
      };
      current.current = next;
      setState(next);
      try {
        localStorage.setItem("lua:media", JSON.stringify(next.media));
        localStorage.setItem(
          "lua:preferences",
          JSON.stringify(next.preferences),
        );
      } catch {
        /* Persistence on the server remains available. */
      }
    }
    async function flush() {
      if (
        !active ||
        readOnly ||
        !ready ||
        sending ||
        !Object.keys(pending.current).length
      )
        return;
      sending = true;
      const changes = pending.current;
      pending.current = {};
      try {
        const response = await fetch("/api/wallpaper", {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf(),
          },
          body: JSON.stringify(changes),
          signal: controller.signal,
        });
        if (!response.ok && response.status !== 409)
          throw Error(
            "Não foi possível sincronizar. Tentaremos novamente quando a conexão voltar.",
          );
        adopt(await response.json());
        if (!readOnly) toast.dismiss("wallpaper-sync");
      } catch (error) {
        if (!active) return;
        pending.current = merge(changes, pending.current);
        toast.error(
          error instanceof Error ? error.message : "Falha de conexão.",
          { id: "wallpaper-sync" },
        );
      } finally {
        sending = false;
        if (active && Object.keys(pending.current).length) {
          clearTimeout(timer);
          timer = setTimeout(() => void flush(), 1500);
        }
      }
    }
    async function refresh() {
      if (!active || polling || sending) return;
      if (ready && Object.keys(pending.current).length) {
        void flush();
        return;
      }
      polling = true;
      try {
        const response = await fetch("/api/wallpaper", {
          headers:
            current.current.revision >= 0
              ? {
                  "If-None-Match": `"lua-wallpaper-${current.current.revision}"`,
                }
              : {},
          cache: "no-store",
          signal: controller.signal,
        });
        if (response.status === 304) {
          ready = true;
          void flush();
          return;
        }
        if (!response.ok) throw Error("Servidor indisponível");
        const incoming: State = await response.json();
        if (
          !ready &&
          !readOnly &&
          incoming.revision === 0 &&
          current.current.revision === -1
        ) {
          // Import the existing local preferences once; concurrent imports use a revision lease.
          let saved = false;
          try {
            saved = !!(
              localStorage.getItem("lua:media") ||
              localStorage.getItem("lua:preferences")
            );
          } catch {
            /* The server also works when browser storage is blocked. */
          }
          if (saved)
            pending.current = merge(
              {
                media: current.current.media,
                preferences: current.current.preferences,
                initialRevision: 0,
              },
              pending.current,
            );
        }
        ready = true;
        adopt(incoming);
        void flush();
      } catch {
        /* Keep the last wallpaper visible while reconnecting. */
      } finally {
        polling = false;
      }
    }
    publish.current = () => {
      clearTimeout(timer);
      timer = setTimeout(() => void flush(), 100);
    };
    void refresh();
    const interval = setInterval(() => void refresh(), 1000);
    const visible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    window.addEventListener("focus", visible);
    document.addEventListener("visibilitychange", visible);
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
      clearInterval(interval);
      window.removeEventListener("focus", visible);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [readOnly]);
  function edit(changes: Changes) {
    if (readOnly) return;
    pending.current = merge(pending.current, changes);
    const next = {
      ...current.current,
      media: changes.media || current.current.media,
      preferences: { ...current.current.preferences, ...changes.preferences },
    };
    current.current = next;
    setState(next);
    publish.current();
  }
  return {
    media: state.media,
    preferences: state.preferences,
    setMedia: (media: Media) => edit({ media }),
    setPreferences: (next: Preferences | ((p: Preferences) => Preferences)) => {
      const preferences =
        typeof next === "function" ? next(current.current.preferences) : next;
      const changes = Object.fromEntries(
        Object.entries(preferences).filter(
          ([key, value]) =>
            current.current.preferences[key as keyof Preferences] !== value,
        ),
      );
      if (Object.keys(changes).length) edit({ preferences: changes });
    },
  };
}
