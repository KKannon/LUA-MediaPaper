import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Expand,
  Globe,
  Instagram,
  Keyboard,
  Maximize2,
  Minus,
  Moon,
  RotateCw,
  Search,
  Shrink,
  Twitter,
  WifiOff,
  X,
  Youtube,
} from "lucide-react";
import { Toaster, toast } from "sonner";
import type { Media, Preferences } from "@/lib/storage";
import { useScreenWakeLock } from "@/lib/use-screen-wake-lock";

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
const apps = [
  {
    name: "YouTube",
    url: "https://www.youtube.com/",
    icon: Youtube,
    color: "#ff3d3d",
  },
  { name: "X", url: "https://x.com/", icon: Twitter, color: "#e7e9ea" },
  {
    name: "Instagram",
    url: "https://www.instagram.com/",
    icon: Instagram,
    color: "#e1306c",
  },
  {
    name: "Google",
    url: "https://www.google.com/",
    icon: Search,
    color: "#8ab4f8",
  },
  { name: "Navegador", url: "", icon: Globe, color: "#c1e697" },
];

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

export function MonitorOS({
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
  const socket = useRef<WebSocket | null>(null);
  const canvases = useRef(new Map<string, HTMLCanvasElement>());
  const windowsRef = useRef<Win[]>([]);
  const focusRef = useRef<string | null>(null);
  const zTop = useRef(1);
  const remoteTarget = useRef<Element | null>(null);
  const keyboard = useRef<HTMLTextAreaElement>(null);
  windowsRef.current = windows;
  focusRef.current = focus;
  useScreenWakeLock(true);

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
    const visible = windows
      .filter((w) => !w.minimized)
      .sort((a, b) => b.z - a.z);
    send({
      type: "layout",
      // While a field of the shell has focus, the PC keyboard types into it instead of the window.
      focus: typing ? null : focus,
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
  }, [windows, focus, typing, send]);

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
    send({ type: "open", url });
  }

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
    } catch {
      /* Not available on every device. */
    }
  }

  const filter = `brightness(${1 - preferences.dim / 100})`;
  const background =
    media.type === "video" ? (
      <video
        className="os-wallpaper"
        src={media.url}
        autoPlay
        loop
        muted
        playsInline
        style={{ objectFit: preferences.fit, filter }}
      />
    ) : (
      <img
        className="os-wallpaper"
        src={media.url}
        alt=""
        style={{ objectFit: preferences.fit, filter }}
      />
    );

  if (!device || !device.approved || forgotten) {
    return (
      <main className="os">
        {background}
        <div className="os-gate">
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
                <em>Telas extras</em>.
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
        </div>
        <Toaster theme="dark" position="top-center" />
      </main>
    );
  }

  return (
    <main className="os" onContextMenu={(e) => e.preventDefault()}>
      {background}
      <header className="os-bar" onDoubleClick={() => void fullscreen()}>
        <span className="flex items-center gap-2">
          <Moon size={13} className="text-primary" />
          Lua OS · {device.name}
        </span>
        <span className="flex items-center gap-3">
          {!connected && (
            <span className="flex items-center gap-1 text-[#deaa68]">
              <WifiOff size={13} /> reconectando
            </span>
          )}
          {edgeInput && <span className="opacity-60">mouse do PC ativo</span>}
          <span>
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
                      e.key === "Enter" && e.currentTarget.form?.requestSubmit()
                    }
                  />
                </form>
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
          <Globe size={16} className="text-primary shrink-0" />
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

      <nav className="os-dock" aria-label="Aplicativos">
        {apps.map((app) => (
          <button
            key={app.name}
            className="os-app"
            onClick={() => (app.url ? open(app.url) : setLauncher((v) => !v))}
            title={app.name}
          >
            <app.icon size={22} color={app.color} />
            <span>{app.name}</span>
          </button>
        ))}
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
