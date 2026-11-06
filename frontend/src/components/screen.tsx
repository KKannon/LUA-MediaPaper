import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ChevronUp,
  Expand,
  Instagram,
  Keyboard,
  LayoutGrid,
  Maximize2,
  Minus,
  Moon,
  Pin,
  PinOff,
  RotateCw,
  Search,
  Shrink,
  Twitter,
  WifiOff,
  X,
  Youtube,
} from "lucide-react";
import { Toaster, toast } from "sonner";
import { Live } from "@/components/live";
import { canFullscreen, keepAwake } from "@/lib/keep-awake";
import type { Media, Preferences } from "@/lib/storage";
import { useWeather } from "@/lib/use-weather";

type Win = {
  id: string;
  url: string;
  title: string;
  x: number;
  y: number;
  w: number;
  h: number;
  z: number;
  minimized: boolean;
  maximized: boolean;
};
type Device = { id: string; name: string; approved: boolean };
const BAR = 30; // Top bar height.
const DOCK = 74; // Space reserved for the dock.
const TITLE = 38; // Window title bar height.
type App = {
  id: string;
  name: string;
  url: string;
  host: string;
  last: string;
};
const DOCK_APPS = 5; // More pinned apps than this go to the Apps menu.
const KNOWN_ICONS: Record<string, [typeof Youtube, string]> = {
  "youtube.com": [Youtube, "#ff3d3d"],
  "x.com": [Twitter, "#e7e9ea"],
  "twitter.com": [Twitter, "#e7e9ea"],
  "instagram.com": [Instagram, "#e1306c"],
  "google.com": [Search, "#8ab4f8"],
};
function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}
/** Brand icon for known sites, the site's own favicon otherwise, a letter if that fails. */
function AppIcon({ app }: { app: Pick<App, "host" | "url" | "name"> }) {
  const [failed, setFailed] = useState(false);
  const known = KNOWN_ICONS[app.host];
  if (known) {
    const [Icon, color] = known;
    return <Icon size={22} color={color} />;
  }
  if (!failed)
    return (
      <img
        className="os-favicon"
        src={new URL("/favicon.ico", app.url).href}
        alt=""
        onError={() => setFailed(true)}
      />
    );
  return (
    <span className="os-letter">{app.name.slice(0, 1).toUpperCase()}</span>
  );
}

function deviceId() {
  let id = localStorage.getItem("lua:monitor-id");
  if (!id) {
    id =
      crypto.randomUUID?.() ??
      Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
        b.toString(16).padStart(2, "0"),
      ).join("");
    localStorage.setItem("lua:monitor-id", id);
  }
  return id;
}
function guessName() {
  const agent = navigator.userAgent;
  if (/iPad|Tablet|Android(?!.*Mobile)/i.test(agent)) return "Tablet";
  if (/iPhone|Android|Mobile/i.test(agent)) return "Celular";
  return "Tela extra";
}
const modifiersOf = (e: {
  altKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
}) =>
  (e.altKey ? 1 : 0) |
  (e.ctrlKey ? 2 : 0) |
  (e.metaKey ? 4 : 0) |
  (e.shiftKey ? 8 : 0);
const textOf = (key: string) =>
  key.length === 1 ? key : key === "Enter" ? "\r" : "";

/** Types into the shell's own inputs when the PC keyboard is on this device. */
function typeInto(element: HTMLInputElement, key: string, text: string) {
  const start = element.selectionStart ?? element.value.length;
  const end = element.selectionEnd ?? start;
  if (text && text !== "\r") element.setRangeText(text, start, end, "end");
  else if (key === "Backspace")
    element.setRangeText(
      "",
      start === end ? Math.max(0, start - 1) : start,
      end,
      "end",
    );
  else if (key === "Delete")
    element.setRangeText("", start, start === end ? end + 1 : end, "end");
  else if (key === "ArrowLeft")
    element.setSelectionRange(Math.max(0, start - 1), Math.max(0, start - 1));
  else if (key === "ArrowRight") element.setSelectionRange(end + 1, end + 1);
  else if (key === "Home") element.setSelectionRange(0, 0);
  else if (key === "End")
    element.setSelectionRange(element.value.length, element.value.length);
  else {
    element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
    if (key === "Escape") element.blur();
    return;
  }
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

export function Screen({
  media,
  preferences,
}: {
  media: Media;
  preferences: Preferences;
}) {
  const [device, setDevice] = useState<Device | null>(null);
  const [connected, setConnected] = useState(false);
  const [forgotten, setForgotten] = useState(false);
  const [edgeInput, setEdgeInput] = useState(false);
  const [windows, setWindows] = useState<Win[]>([]);
  const [focus, setFocus] = useState<string | null>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const [now, setNow] = useState(new Date());
  const [launcher, setLauncher] = useState(false);
  const [full, setFull] = useState(false);
  const [typing, setTyping] = useState(false);
  const [apps, setApps] = useState<App[]>([]);
  const [menu, setMenu] = useState(false);
  const [appMenu, setAppMenu] = useState<string | null>(null);
  // The wallpaper (lock screen) is in front after the idle time; dragging up shows the system again.
  const [locked, setLocked] = useState(false);
  const [gate, setGate] = useState(false);
  const [pull, setPull] = useState(0);
  const [hint, setHint] = useState(false);
  const [promptHidden, setPromptHidden] = useState(false);
  const lastActivity = useRef(Date.now());
  const hintTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const lockedRef = useRef(false);
  const socket = useRef<WebSocket | null>(null);
  const canvases = useRef(new Map<string, HTMLCanvasElement>());
  const windowsRef = useRef<Win[]>([]);
  const focusRef = useRef<string | null>(null);
  const zTop = useRef(1);
  const remoteTarget = useRef<Element | null>(null);
  const keyboard = useRef<HTMLTextAreaElement>(null);
  windowsRef.current = windows;
  focusRef.current = focus;
  lockedRef.current = locked;
  const approved = !!device?.approved && !forgotten;
  const weather = useWeather(
    preferences.weather && !!preferences.city,
    preferences.city ? `${preferences.city.lat},${preferences.city.lon}` : "",
  );
  const activity = useCallback(() => {
    lastActivity.current = Date.now();
  }, []);

  // Idle: fade to the wallpaper. Video playing in the focused window counts as activity (see frames).
  useEffect(() => {
    const timer = setInterval(() => {
      if (
        approved &&
        !lockedRef.current &&
        preferences.idle > 0 &&
        Date.now() - lastActivity.current > preferences.idle * 1000
      ) {
        setLocked(true);
        setMenu(false);
        setLauncher(false);
        setAppMenu(null);
        (document.activeElement as HTMLElement | null)?.blur?.();
      }
    }, 1000);
    const events = [
      "pointermove",
      "pointerdown",
      "keydown",
      "wheel",
      "touchstart",
    ];
    for (const name of events) window.addEventListener(name, activity, true);
    return () => {
      clearInterval(timer);
      for (const name of events)
        window.removeEventListener(name, activity, true);
    };
  }, [approved, preferences.idle, activity]);

  // Unlocking: drag up with touch, the device's mouse or the PC cursor (its synthetic events bubble here too).
  function unlockStart(event: React.PointerEvent) {
    const startY = event.clientY;
    let distance = 0;
    const move = (e: PointerEvent) => {
      distance = Math.min(0, e.clientY - startY);
      setPull(distance);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setPull(0);
      if (distance < -Math.max(70, window.innerHeight * 0.15)) unlock();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }
  function unlock() {
    activity();
    setHint(false);
    if (approved) setLocked(false);
    else setGate(true);
  }
  function showHint() {
    setHint(true);
    clearTimeout(hintTimer.current);
    hintTimer.current = setTimeout(() => setHint(false), 2500);
  }

  const send = useCallback((message: object) => {
    if (socket.current?.readyState === WebSocket.OPEN)
      socket.current.send(JSON.stringify(message));
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    const change = () => setFull(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", change);
    const fields = () =>
      setTyping(
        document.activeElement instanceof HTMLInputElement &&
          !!document.activeElement.closest(".os-title, .os-launcher"),
      );
    const left = () => setTimeout(fields);
    document.addEventListener("focusin", fields);
    document.addEventListener("focusout", left);
    return () => {
      clearInterval(timer);
      document.removeEventListener("fullscreenchange", change);
      document.removeEventListener("focusin", fields);
      document.removeEventListener("focusout", left);
    };
  }, []);

  // Geometry of a newly opened window: cascaded, 70% of the desktop.
  const place = useCallback((index: number) => {
    const width = window.innerWidth,
      height = window.innerHeight - BAR - DOCK;
    const w = Math.max(320, Math.round(width * 0.72)),
      h = Math.max(240, Math.round(height * 0.8));
    const shift = (index % 6) * 28;
    return {
      x: Math.min(Math.max(8, (width - w) / 2 + shift - 70), width - w),
      y: BAR + 10 + shift,
      w,
      h,
    };
  }, []);

  useEffect(() => {
    let closed = false,
      retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function connect() {
      let port: number | null = null;
      try {
        const status = await (
          await fetch("/api/status", { cache: "no-store" })
        ).json();
        port = status.monitorPort;
      } catch {
        /* Retried below. */
      }
      if (closed) return;
      if (!port) {
        timer = setTimeout(connect, 3000);
        return;
      }
      const ws = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.hostname}:${port}/`,
      );
      ws.binaryType = "arraybuffer";
      socket.current = ws;
      ws.onopen = () => {
        retry = 0;
        setConnected(true);
        ws.send(
          JSON.stringify({
            type: "hello",
            id: deviceId(),
            name: localStorage.getItem("lua:monitor-name") || guessName(),
            width: window.innerWidth,
            height: window.innerHeight,
            scale: window.devicePixelRatio,
          }),
        );
      };
      ws.onclose = () => {
        setConnected(false);
        setCursor(null);
        if (!closed)
          timer = setTimeout(connect, Math.min(10000, 800 * 2 ** retry++));
      };
      ws.onmessage = async (event) => {
        if (event.data instanceof ArrayBuffer) {
          const bytes = new Uint8Array(event.data);
          const id = new TextDecoder().decode(bytes.subarray(1, 1 + bytes[0]));
          try {
            const bitmap = await createImageBitmap(
              new Blob([bytes.subarray(1 + bytes[0])], { type: "image/jpeg" }),
            );
            const canvas = canvases.current.get(id);
            if (id === focusRef.current && !lockedRef.current) activity();
            if (canvas) {
              if (
                canvas.width !== bitmap.width ||
                canvas.height !== bitmap.height
              ) {
                canvas.width = bitmap.width;
                canvas.height = bitmap.height;
              }
              canvas.getContext("2d")?.drawImage(bitmap, 0, 0);
            }
            bitmap.close();
          } finally {
            ws.send(JSON.stringify({ type: "ack", win: id }));
          }
          return;
        }
        const message = JSON.parse(event.data);
        if (message.type === "state") {
          setDevice(message.device);
          setApps(message.device.apps ?? []);
          setEdgeInput(message.edgeInput);
          setForgotten(false);
          setWindows((old) => {
            const known = new Map(old.map((w) => [w.id, w]));
            return message.windows.map((w: Win, index: number) => {
              const existing = known.get(w.id);
              if (existing) return existing;
              const geometry = place(index);
              ws.send(
                JSON.stringify({
                  type: "resize",
                  win: w.id,
                  w: geometry.w,
                  h: geometry.h - TITLE,
                }),
              );
              return {
                ...w,
                ...geometry,
                z: zTop.current++,
                minimized: false,
                maximized: false,
              };
            });
          });
        } else if (message.type === "window") {
          setWindows((old) => {
            const geometry = place(old.length);
            const next = {
              ...message.window,
              ...geometry,
              z: zTop.current++,
              minimized: false,
              maximized: false,
            };
            ws.send(
              JSON.stringify({
                type: "resize",
                win: next.id,
                w: geometry.w,
                h: geometry.h - TITLE,
              }),
            );
            return [...old, next];
          });
          setFocus(message.window.id);
        } else if (message.type === "apps") {
          setApps(message.apps);
        } else if (message.type === "title") {
          setWindows((old) =>
            old.map((w) =>
              w.id === message.win
                ? { ...w, title: message.title, url: message.url }
                : w,
            ),
          );
        } else if (message.type === "closed") {
          setWindows((old) => old.filter((w) => w.id !== message.win));
        } else if (message.type === "focus") {
          (document.activeElement as HTMLElement | null)?.blur?.();
          setFocus(message.win);
          setWindows((old) =>
            old.map((w) =>
              w.id === message.win
                ? { ...w, z: zTop.current++, minimized: false }
                : w,
            ),
          );
        } else if (message.type === "cursor") {
          setCursor(message.visible ? { x: message.x, y: message.y } : null);
          if (message.visible) {
            activity();
            if (lockedRef.current) showHint();
          }
          if (message.visible && remoteTarget.current)
            (
              document.elementFromPoint(message.x, message.y) ?? document.body
            ).dispatchEvent(
              new PointerEvent("pointermove", {
                bubbles: true,
                clientX: message.x,
                clientY: message.y,
                pointerType: "mouse",
                pointerId: 99,
                buttons: 1,
              }),
            );
        } else if (message.type === "pointer") {
          const target = document.elementFromPoint(message.x, message.y);
          if (!target) return;
          const init = {
            bubbles: true,
            cancelable: true,
            clientX: message.x,
            clientY: message.y,
            button:
              { left: 0, middle: 1, right: 2 }[message.button as string] ?? 0,
            pointerId: 99,
            pointerType: "mouse",
          };
          if (message.action === "down") {
            remoteTarget.current = target;
            target.dispatchEvent(
              new PointerEvent("pointerdown", { ...init, buttons: 1 }),
            );
            target.dispatchEvent(new MouseEvent("mousedown", init));
            const field = target.closest(
              "input, textarea",
            ) as HTMLElement | null;
            if (field) field.focus();
            else (document.activeElement as HTMLElement | null)?.blur?.();
          } else if (message.action === "up") {
            target.dispatchEvent(new PointerEvent("pointerup", init));
            target.dispatchEvent(new MouseEvent("mouseup", init));
            const pressed = remoteTarget.current;
            remoteTarget.current = null;
            if (
              pressed &&
              (pressed === target ||
                pressed.contains(target) ||
                target.contains(pressed)) &&
              init.button === 0
            )
              pressed.dispatchEvent(new MouseEvent("click", init));
            else if (pressed && init.button === 2)
              pressed.dispatchEvent(new MouseEvent("contextmenu", init));
          } else
            target.dispatchEvent(
              new WheelEvent("wheel", {
                ...init,
                deltaX: message.dx,
                deltaY: message.dy,
              }),
            );
        } else if (message.type === "key") {
          const active = document.activeElement;
          if (message.down && active instanceof HTMLInputElement)
            typeInto(active, message.key, message.text);
        } else if (message.type === "error") {
          toast.error(message.message);
        } else if (message.type === "forgotten") {
          setForgotten(true);
          setWindows([]);
        }
      };
    }
    void connect();
    const resize = () =>
      send({
        type: "size",
        width: window.innerWidth,
        height: window.innerHeight,
        scale: window.devicePixelRatio,
      });
    window.addEventListener("resize", resize);
    return () => {
      closed = true;
      clearTimeout(timer);
      window.removeEventListener("resize", resize);
      socket.current?.close();
    };
  }, [place, send]);

  // Tell the server where each window is, so the PC cursor can reach the right one.
  useEffect(() => {
    const visible =
      locked || !approved
        ? []
        : windows.filter((w) => !w.minimized).sort((a, b) => b.z - a.z);
    send({
      type: "layout",
      // While a field of the shell has focus, the PC keyboard types into it instead of the window.
      focus: typing || locked ? null : focus,
      rects: visible.map((w) => {
        const g = geometry(w);
        return {
          win: w.id,
          x: g.x,
          y: g.y + TITLE,
          w: g.w,
          h: g.h - TITLE,
          fx: g.x,
          fy: g.y,
          fw: g.w,
          fh: g.h,
        };
      }),
    });
  }, [windows, focus, typing, locked, approved, send]);

  function geometry(w: Win) {
    return w.maximized
      ? {
          x: 0,
          y: BAR,
          w: window.innerWidth,
          h: window.innerHeight - BAR - DOCK + 8,
        }
      : w;
  }
  function update(id: string, changes: Partial<Win>, resize = false) {
    setWindows((old) =>
      old.map((w) => {
        if (w.id !== id) return w;
        const next = { ...w, ...changes };
        if (resize) {
          const g = geometry(next);
          send({ type: "resize", win: id, w: g.w, h: g.h - TITLE });
        }
        return next;
      }),
    );
  }
  function raise(id: string) {
    setFocus(id);
    update(id, { z: zTop.current++, minimized: false });
  }
  function open(url: string) {
    setLauncher(false);
    setMenu(false);
    send({ type: "open", url });
  }
  function launch(app: App) {
    setMenu(false);
    setAppMenu(null);
    send({ type: "launch", app: app.id });
  }
  const pinnedHosts = new Set(apps.map((a) => a.host));
  // Long press (touch) or right click opens the small menu to unpin a dock icon.
  const press = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const pressed = useRef(false);

  // Dragging a title bar or a resize corner, with touch, mouse or the PC cursor.
  function drag(event: React.PointerEvent, w: Win, mode: "move" | "resize") {
    if (w.maximized && mode === "move") return;
    event.preventDefault();
    raise(w.id);
    const start = { x: event.clientX, y: event.clientY, w: { ...w } };
    let last = start.w;
    const move = (e: PointerEvent) => {
      const dx = e.clientX - start.x,
        dy = e.clientY - start.y;
      last =
        mode === "move"
          ? {
              ...start.w,
              x: Math.min(
                Math.max(start.w.x + dx, 60 - start.w.w),
                window.innerWidth - 60,
              ),
              y: Math.min(
                Math.max(start.w.y + dy, BAR),
                window.innerHeight - DOCK - 20,
              ),
            }
          : {
              ...start.w,
              w: Math.max(300, start.w.w + dx),
              h: Math.max(220, start.w.h + dy),
            };
      update(w.id, { x: last.x, y: last.y, w: last.w, h: last.h });
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (mode === "resize") update(w.id, {}, true);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  // Input from this device's own touch screen, mouse or keyboard.
  const touch = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  function contentPointer(
    event: React.PointerEvent<HTMLCanvasElement>,
    w: Win,
    action: "down" | "move" | "up",
  ) {
    if (event.pointerId === 99) return; // Synthetic events from the PC cursor are handled by the server.
    const box = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - box.left,
      y = event.clientY - box.top;
    if (action === "down") {
      raise(w.id);
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    if (event.pointerType === "touch") {
      // Drag scrolls the page; a tap is a click.
      if (action === "down") touch.current = { x, y, moved: false };
      else if (touch.current && action === "move") {
        const dx = touch.current.x - x,
          dy = touch.current.y - y;
        if (touch.current.moved || Math.abs(dx) + Math.abs(dy) > 8) {
          touch.current = { x, y, moved: true };
          send({
            type: "mouse",
            win: w.id,
            action: "wheel",
            x,
            y,
            dx: dx * 1.6,
            dy: dy * 1.6,
          });
        }
      } else if (touch.current && action === "up") {
        if (!touch.current.moved)
          for (const a of ["move", "down", "up"])
            send({ type: "mouse", win: w.id, action: a, x, y, button: "left" });
        touch.current = null;
      }
      return;
    }
    send({
      type: "mouse",
      win: w.id,
      action,
      x,
      y,
      button: ["left", "middle", "right"][event.button] ?? "left",
      modifiers: modifiersOf(event),
    });
  }

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (!focusRef.current || target.closest?.("input, textarea")) return;
      event.preventDefault();
      send({
        type: "key",
        win: focusRef.current,
        down: event.type === "keydown",
        vk: event.keyCode,
        key: event.key,
        code: event.code,
        text:
          event.type === "keydown" && !event.ctrlKey && !event.metaKey
            ? textOf(event.key)
            : "",
        modifiers: modifiersOf(event),
      });
    };
    window.addEventListener("keydown", key);
    window.addEventListener("keyup", key);
    return () => {
      window.removeEventListener("keydown", key);
      window.removeEventListener("keyup", key);
    };
  }, [send]);

  async function fullscreen() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
      if (preferences.keepAwake) void keepAwake();
    } catch {
      /* Not available on every device. */
    }
  }

  const docked = apps.length > DOCK_APPS ? apps.slice(0, DOCK_APPS) : apps;
  const front = approved ? (locked ? "live" : "os") : gate ? "gate" : "live";
  return (
    <main
      className={`screen ${front === "os" ? "unlocked" : "locked"}`}
      style={
        {
          "--pull": `${pull}px`,
          "--fade": Math.max(0, 1 + pull / 300),
        } as React.CSSProperties
      }
      onContextMenu={(e) => e.preventDefault()}
      onPointerDown={(e) => {
        if (preferences.keepAwake) void keepAwake();
        // On the wallpaper, any press can start the drag up; controls on it stop propagation.
        if (front === "live") unlockStart(e);
      }}
      onPointerMove={() => front === "live" && showHint()}
    >
      <Live
        media={media}
        preferences={preferences}
        weather={weather}
        interactive={false}
      />

      {front === "live" && (
        <div
          className={`screen-hint ${hint || !approved ? "visible" : ""}`}
          role="status"
        >
          <ChevronUp size={18} />
          {approved
            ? "Arraste para cima para desbloquear"
            : connected
              ? "Arraste para cima · aprove esta tela no PC para usar o Lua OS"
              : "Conectando ao Lua…"}
        </div>
      )}

      {front === "gate" && (
        <div className="os-gate" onPointerDown={(e) => e.stopPropagation()}>
          <Moon size={30} className="text-primary" />
          <h1>
            {forgotten
              ? "Esta tela foi removida."
              : connected
                ? "Aguardando aprovação no PC"
                : "Conectando ao Lua…"}
          </h1>
          {forgotten ? (
            <button
              className="os-button"
              onClick={() => {
                localStorage.removeItem("lua:monitor-id");
                location.reload();
              }}
            >
              Conectar de novo
            </button>
          ) : connected ? (
            <>
              <p>
                No computador, abra a Home do Lua MediaPaper e aprove{" "}
                <strong>{device?.name ?? guessName()}</strong> em{" "}
                <em>Telas extras</em>. Enquanto isso, esta tela mostra o
                wallpaper.
              </p>
              <label className="os-name">
                Nome desta tela
                <input
                  defaultValue={
                    localStorage.getItem("lua:monitor-name") ||
                    device?.name ||
                    guessName()
                  }
                  maxLength={40}
                  onBlur={(e) => {
                    localStorage.setItem("lua:monitor-name", e.target.value);
                    socket.current?.close();
                  }}
                />
              </label>
            </>
          ) : (
            <p>Verifique se o PC está ligado e na mesma rede.</p>
          )}
          <button className="os-link" onClick={() => setGate(false)}>
            Voltar ao wallpaper
          </button>
        </div>
      )}

      {approved && (
        <div className="os-layer" aria-hidden={front !== "os"}>
          <header className="os-bar" onDoubleClick={() => void fullscreen()}>
            <span className="flex items-center gap-2">
              <Moon size={13} className="text-primary" />
              Lua OS · {device?.name}
            </span>
            <span className="flex items-center gap-3">
              {!connected && (
                <span className="flex items-center gap-1 text-[#deaa68]">
                  <WifiOff size={13} /> reconectando
                </span>
              )}
              {edgeInput && (
                <span className="opacity-60 max-sm:hidden">
                  mouse do PC ativo
                </span>
              )}
              {weather && (
                <span title={weather.description}>
                  {weather.temperature}° {weather.city}
                </span>
              )}
              <span className="max-sm:hidden">
                {now.toLocaleDateString("pt-BR", {
                  weekday: "short",
                  day: "2-digit",
                  month: "short",
                })}
              </span>
              <strong>
                {now.toLocaleTimeString("pt-BR", {
                  hour: "2-digit",
                  minute: "2-digit",
                  hour12: !preferences.hour24,
                })}
              </strong>
              <button
                aria-label={full ? "Sair da tela cheia" : "Tela cheia"}
                onClick={() => void fullscreen()}
              >
                {full ? <Shrink size={14} /> : <Expand size={14} />}
              </button>
            </span>
          </header>

          {windows
            .filter((w) => !w.minimized)
            .map((w) => {
              const g = geometry(w);
              return (
                <section
                  key={w.id}
                  className={`os-window ${focus === w.id ? "focused" : ""}`}
                  style={{
                    left: g.x,
                    top: g.y,
                    width: g.w,
                    height: g.h,
                    zIndex: w.z,
                  }}
                  onPointerDown={() => focus !== w.id && raise(w.id)}
                >
                  <div
                    className="os-title"
                    onPointerDown={(e) =>
                      (e.target as HTMLElement).closest("button, input") ||
                      drag(e, w, "move")
                    }
                    onDoubleClick={(e) =>
                      (e.target as HTMLElement).closest("button, input") ||
                      update(w.id, { maximized: !w.maximized }, true)
                    }
                  >
                    <button
                      aria-label="Voltar"
                      onClick={() =>
                        send({ type: "nav", win: w.id, action: "back" })
                      }
                    >
                      <ArrowLeft size={14} />
                    </button>
                    <button
                      aria-label="Avançar"
                      onClick={() =>
                        send({ type: "nav", win: w.id, action: "forward" })
                      }
                    >
                      <ArrowRight size={14} />
                    </button>
                    <button
                      aria-label="Recarregar"
                      onClick={() =>
                        send({ type: "nav", win: w.id, action: "reload" })
                      }
                    >
                      <RotateCw size={13} />
                    </button>
                    <form
                      className="os-address"
                      onSubmit={(e) => {
                        e.preventDefault();
                        const input = e.currentTarget.elements.namedItem(
                          "url",
                        ) as HTMLInputElement;
                        send({
                          type: "nav",
                          win: w.id,
                          action: "go",
                          url: input.value,
                        });
                        input.blur();
                      }}
                    >
                      <input
                        name="url"
                        key={w.url}
                        defaultValue={w.url}
                        title={w.title}
                        aria-label="Endereço"
                        onKeyDown={(e) =>
                          e.key === "Enter" &&
                          e.currentTarget.form?.requestSubmit()
                        }
                      />
                    </form>
                    {/^https?:/.test(w.url) && (
                      <button
                        className={`os-pin ${pinnedHosts.has(hostOf(w.url)) ? "pinned" : ""}`}
                        aria-label={
                          pinnedHosts.has(hostOf(w.url))
                            ? `Desafixar ${hostOf(w.url)}`
                            : `Fixar ${hostOf(w.url)} na barra`
                        }
                        title={
                          pinnedHosts.has(hostOf(w.url))
                            ? "Fixado na barra · abre na última página visitada"
                            : "Fixar este site na barra"
                        }
                        onClick={() => {
                          const app = apps.find(
                            (a) => a.host === hostOf(w.url),
                          );
                          if (app) send({ type: "unpin", app: app.id });
                          else {
                            send({ type: "pin", win: w.id });
                            toast.success(`${hostOf(w.url)} fixado na barra.`);
                          }
                        }}
                      >
                        {pinnedHosts.has(hostOf(w.url)) ? (
                          <Pin size={13} fill="currentColor" />
                        ) : (
                          <Pin size={13} />
                        )}
                      </button>
                    )}
                    <button
                      aria-label="Minimizar"
                      onClick={() => update(w.id, { minimized: true })}
                    >
                      <Minus size={14} />
                    </button>
                    <button
                      aria-label={w.maximized ? "Restaurar" : "Maximizar"}
                      onClick={() =>
                        update(w.id, { maximized: !w.maximized }, true)
                      }
                    >
                      <Maximize2 size={13} />
                    </button>
                    <button
                      aria-label="Fechar"
                      className="close"
                      onClick={() => send({ type: "close", win: w.id })}
                    >
                      <X size={14} />
                    </button>
                  </div>
                  <canvas
                    ref={(element) => {
                      if (element) canvases.current.set(w.id, element);
                      else canvases.current.delete(w.id);
                    }}
                    className="os-content"
                    tabIndex={-1}
                    onPointerDown={(e) => contentPointer(e, w, "down")}
                    onPointerMove={(e) => contentPointer(e, w, "move")}
                    onPointerUp={(e) => contentPointer(e, w, "up")}
                    onWheel={(e) => {
                      const box = e.currentTarget.getBoundingClientRect();
                      send({
                        type: "mouse",
                        win: w.id,
                        action: "wheel",
                        x: e.clientX - box.left,
                        y: e.clientY - box.top,
                        dx: e.deltaX,
                        dy: e.deltaY,
                      });
                    }}
                  />
                  {!w.maximized && (
                    <div
                      className="os-resize"
                      onPointerDown={(e) => drag(e, w, "resize")}
                    />
                  )}
                </section>
              );
            })}

          {launcher && (
            <form
              className="os-launcher"
              onSubmit={(e) => {
                e.preventDefault();
                open(
                  (
                    e.currentTarget.elements.namedItem(
                      "address",
                    ) as HTMLInputElement
                  ).value,
                );
              }}
            >
              <Search size={16} className="text-primary shrink-0" />
              <input
                name="address"
                autoFocus
                placeholder="Digite um site ou pesquise no Google"
                aria-label="Site ou pesquisa"
                onKeyDown={(e) =>
                  e.key === "Enter" && e.currentTarget.form?.requestSubmit()
                }
              />
              <button
                type="button"
                aria-label="Fechar"
                onClick={() => setLauncher(false)}
              >
                <X size={14} />
              </button>
            </form>
          )}

          {menu && (
            <section className="os-menu" aria-label="Apps">
              <h2>Apps fixados</h2>
              <div className="os-menu-grid">
                {apps.map((app) => (
                  <div key={app.id} className="os-menu-app">
                    <button onClick={() => launch(app)} title={app.last}>
                      <AppIcon app={app} />
                      <span>{app.name}</span>
                    </button>
                    <button
                      className="os-unpin"
                      aria-label={`Desafixar ${app.name}`}
                      title="Desafixar"
                      onClick={() => send({ type: "unpin", app: app.id })}
                    >
                      <PinOff size={12} />
                    </button>
                  </div>
                ))}
              </div>
              <p>
                Abra um site pela pesquisa e toque no alfinete da janela para
                fixá-lo. Cada app reabre na última página visitada.
              </p>
            </section>
          )}

          {appMenu && (
            <div className="os-popover" style={{ left: "50%" }}>
              <span>{apps.find((a) => a.id === appMenu)?.name}</span>
              <button
                onClick={() => {
                  send({ type: "unpin", app: appMenu });
                  setAppMenu(null);
                }}
              >
                <PinOff size={13} /> Desafixar
              </button>
              <button onClick={() => setAppMenu(null)}>
                <X size={13} />
              </button>
            </div>
          )}

          <nav className="os-dock" aria-label="Aplicativos">
            {docked.map((app) => (
              <button
                key={app.id}
                className="os-app"
                title={app.name}
                onClick={() => {
                  if (pressed.current) pressed.current = false;
                  else launch(app);
                }}
                onContextMenu={(e) => {
                  e.preventDefault();
                  setAppMenu(app.id);
                }}
                onPointerDown={() => {
                  pressed.current = false;
                  press.current = setTimeout(() => {
                    pressed.current = true;
                    setAppMenu(app.id);
                  }, 600);
                }}
                onPointerUp={() => clearTimeout(press.current)}
                onPointerLeave={() => clearTimeout(press.current)}
              >
                <AppIcon app={app} />
                <span>{app.name}</span>
              </button>
            ))}
            {apps.length > DOCK_APPS && (
              <button
                className={`os-app ${menu ? "active" : ""}`}
                title="Todos os apps"
                onClick={() => {
                  setMenu((v) => !v);
                  setLauncher(false);
                }}
              >
                <LayoutGrid size={22} color="#c1e697" />
                <span>Apps</span>
              </button>
            )}
            <button
              className="os-app"
              title="Pesquisar ou abrir um site"
              onClick={() => {
                setLauncher((v) => !v);
                setMenu(false);
              }}
            >
              <Search size={22} color="#c1e697" />
              <span>Pesquisar</span>
            </button>
            {windows.length > 0 && <i className="os-divider" />}
            {windows.map((w) => (
              <button
                key={w.id}
                className={`os-task ${focus === w.id && !w.minimized ? "active" : ""}`}
                onClick={() =>
                  w.minimized || focus !== w.id
                    ? raise(w.id)
                    : update(w.id, { minimized: true })
                }
                title={w.title || w.url}
              >
                {(w.title || w.url || "Nova janela")
                  .replace(/^https?:\/\/(www\.)?/, "")
                  .slice(0, 18)}
              </button>
            ))}
            {focus && windows.some((w) => w.id === focus) && (
              <button
                className="os-app"
                title="Teclado na tela"
                onClick={() => keyboard.current?.focus()}
              >
                <Keyboard size={22} />
                <span>Teclado</span>
              </button>
            )}
          </nav>
        </div>
      )}

      {canFullscreen() && !full && !promptHidden && (
        <div
          className="screen-prompt"
          onPointerDown={(e) => e.stopPropagation()}
        >
          <Expand size={15} className="text-primary shrink-0" />
          <span>
            Use em tela cheia: a tela do aparelho não apaga e tudo fica maior.
          </span>
          <button className="os-button" onClick={() => void fullscreen()}>
            Tela cheia
          </button>
          <button
            aria-label="Agora não"
            className="opacity-70"
            onClick={() => setPromptHidden(true)}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Hidden field that opens the on-screen keyboard and forwards what is typed to the focused window. */}
      <textarea
        ref={keyboard}
        className="os-keyboard"
        aria-label="Teclado na tela"
        autoCapitalize="off"
        autoCorrect="off"
        onBeforeInput={(e) => {
          const native = e.nativeEvent as InputEvent;
          e.preventDefault();
          if (!focus) return;
          if (native.inputType === "insertText" && native.data)
            send({ type: "text", win: focus, text: native.data });
          else if (native.inputType === "insertLineBreak")
            for (const down of [true, false])
              send({
                type: "key",
                win: focus,
                down,
                vk: 13,
                key: "Enter",
                code: "Enter",
                text: down ? "\r" : "",
              });
        }}
        onKeyDown={(e) => {
          if (
            !focus ||
            ![
              "Backspace",
              "Enter",
              "Tab",
              "ArrowLeft",
              "ArrowRight",
              "ArrowUp",
              "ArrowDown",
              "Escape",
            ].includes(e.key)
          )
            return;
          e.preventDefault();
          e.stopPropagation();
          for (const down of [true, false])
            send({
              type: "key",
              win: focus,
              down,
              vk: e.keyCode,
              key: e.key,
              code: e.code,
              text: down ? textOf(e.key) : "",
            });
        }}
      />

      {cursor && (
        <svg
          className="os-cursor"
          style={{ left: cursor.x, top: cursor.y }}
          width="22"
          height="22"
          viewBox="0 0 24 24"
          aria-hidden
        >
          <path
            d="M4 2l15 11.5-6.6.9 3.9 7.4-2.7 1.4-3.9-7.5L4 20z"
            fill="#fff"
            stroke="#101113"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
        </svg>
      )}
      <Toaster theme="dark" position="top-center" />
    </main>
  );
}
