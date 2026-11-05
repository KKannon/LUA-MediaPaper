import { useEffect, useRef, useState } from "react";
import {
  Check,
  Monitor,
  MonitorSmartphone,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { csrf } from "@/lib/storage";

type Side = "left" | "right" | "top" | "bottom";
type Screen = {
  id: string;
  name: string;
  width: number;
  height: number;
  approved: boolean;
  side: Side | null;
  offset: number;
  online: boolean;
};
type Snapshot = {
  screen: { width: number; height: number };
  edgeInput: boolean;
  running: boolean;
  devices: Screen[];
};

/** Nearest PC edge for a device dropped at (x, y), in PC pixels relative to the PC screen's top-left corner. */
export function snap(
  x: number,
  y: number,
  w: number,
  h: number,
  screen: { width: number; height: number },
) {
  const cx = x + w / 2,
    cy = y + h / 2;
  // Distance outside the screen along each axis, normalized so wide and tall screens behave the same.
  const horizontal =
    cx < screen.width / 2
      ? -cx / screen.width
      : (cx - screen.width) / screen.width;
  const vertical =
    cy < screen.height / 2
      ? -cy / screen.height
      : (cy - screen.height) / screen.height;
  const clamp = (value: number, size: number, length: number) =>
    Math.round(Math.min(Math.max(value, 60 - size), length - 60));
  if (horizontal >= vertical)
    return {
      side: (cx < screen.width / 2 ? "left" : "right") as Side,
      offset: clamp(y, h, screen.height),
    };
  return {
    side: (cy < screen.height / 2 ? "top" : "bottom") as Side,
    offset: clamp(x, w, screen.width),
  };
}
export function position(
  device: Pick<Screen, "side" | "offset" | "width" | "height">,
  screen: { width: number; height: number },
) {
  switch (device.side) {
    case "left":
      return { x: -device.width, y: device.offset };
    case "right":
      return { x: screen.width, y: device.offset };
    case "top":
      return { x: device.offset, y: -device.height };
    default:
      return { x: device.offset, y: screen.height };
  }
}

async function change(id: string, method: "PATCH" | "DELETE", body?: object) {
  const r = await fetch(`/api/monitors/${id}`, {
    method,
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok)
    throw Error(
      (await r.json().catch(() => ({}))).error ||
        "Não foi possível alterar a tela.",
    );
}

export function ScreensPanel() {
  const [data, setData] = useState<Snapshot | null>(null);
  const [networkUrls, setNetworkUrls] = useState<string[]>([]);
  const [dragging, setDragging] = useState<{
    id: string;
    x: number;
    y: number;
  } | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const area = useRef<HTMLDivElement>(null);
  const [areaWidth, setAreaWidth] = useState(640);

  useEffect(() => {
    let active = true;
    const load = () =>
      fetch("/api/monitors", { cache: "no-store" })
        .then((r) => r.json())
        .then((d) => active && setData(d))
        .catch(() => {});
    void load();
    fetch("/api/status")
      .then((r) => r.json())
      .then((s) => active && setNetworkUrls(s.networkUrls ?? []))
      .catch(() => {});
    const timer = setInterval(load, 2000);
    const observer = new ResizeObserver(([entry]) =>
      setAreaWidth(entry.contentRect.width),
    );
    if (area.current) observer.observe(area.current);
    return () => {
      active = false;
      clearInterval(timer);
      observer.disconnect();
    };
  }, []);

  async function run(action: Promise<void>, success?: string) {
    try {
      await action;
      if (success) toast.success(success);
      const r = await fetch("/api/monitors", { cache: "no-store" });
      setData(await r.json());
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Falha ao alterar a tela.");
    }
  }

  const screen = data?.screen ?? { width: 1920, height: 1080 };
  const approved = data?.devices.filter((d) => d.approved) ?? [];
  const pending = data?.devices.filter((d) => !d.approved) ?? [];
  // Scale so the PC plus a device on every side fits the drawing area.
  const tallest = Math.max(
    screen.height * 0.6,
    ...approved.map((d) => d.height),
  );
  const widest = Math.max(screen.width * 0.4, ...approved.map((d) => d.width));
  const scale = Math.min(
    (areaWidth - 24) / (screen.width + widest * 2),
    300 / (screen.height + tallest * 2),
  );
  const height = (screen.height + tallest * 2) * scale + 24;
  const origin = {
    x: (areaWidth - screen.width * scale) / 2,
    y: (height - screen.height * scale) / 2,
  };
  const placed = approved.filter((d) => d.side || dragging?.id === d.id);
  const loose = approved.filter((d) => !d.side);

  function startDrag(
    event: React.PointerEvent,
    device: Screen,
    from: { x: number; y: number },
  ) {
    event.preventDefault();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    const start = { x: event.clientX, y: event.clientY };
    let last = from;
    const move = (e: PointerEvent) => {
      last = {
        x: from.x + (e.clientX - start.x) / scale,
        y: from.y + (e.clientY - start.y) / scale,
      };
      setDragging({ id: device.id, ...last });
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setDragging(null);
      const target = snap(last.x, last.y, device.width, device.height, screen);
      setData(
        (d) =>
          d && {
            ...d,
            devices: d.devices.map((x) =>
              x.id === device.id ? { ...x, ...target } : x,
            ),
          },
      );
      void run(change(device.id, "PATCH", target));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  const monitorUrl = (networkUrls[0] ?? `${location.origin}/`) + "monitor";
  return (
    <section className="panel screens-panel">
      <div className="flex justify-between items-start gap-4 mb-1">
        <div>
          <h2 className="panel-heading !mb-1">
            <MonitorSmartphone />
            Telas extras
          </h2>
          <p className="helper !mt-0">
            Abra <strong className="text-foreground">{monitorUrl}</strong> no
            celular ou tablet. Arraste a tela para o lado do PC por onde o mouse
            deve passar.
          </p>
        </div>
        <span className="pill shrink-0">
          {data?.edgeInput
            ? "Mouse compartilhado ativo"
            : data?.running
              ? "Somente toque"
              : "Indisponível"}
        </span>
      </div>

      {pending.map((device) => (
        <div key={device.id} className="screen-request">
          <MonitorSmartphone size={16} className="text-primary shrink-0" />
          <span className="grow">
            <strong>{device.name}</strong> quer ser uma tela extra ·{" "}
            {device.width}×{device.height}
          </span>
          <button
            className="screen-action primary"
            onClick={() =>
              void run(
                change(device.id, "PATCH", { approved: true }),
                "Tela aprovada.",
              )
            }
          >
            <Check size={13} /> Aprovar
          </button>
          <button
            className="screen-action"
            onClick={() => void run(change(device.id, "DELETE"))}
          >
            <X size={13} /> Recusar
          </button>
        </div>
      ))}

      <div ref={area} className="screens-area" style={{ height }}>
        <div
          className="screen-pc"
          style={{
            left: origin.x,
            top: origin.y,
            width: screen.width * scale,
            height: screen.height * scale,
          }}
        >
          <Monitor size={18} />
          <span>Este PC</span>
          <small>
            {screen.width}×{screen.height}
          </small>
        </div>
        {placed.map((device) => {
          const at =
            dragging?.id === device.id ? dragging : position(device, screen);
          return (
            <div
              key={device.id}
              className={`screen-device ${device.online ? "online" : ""} ${dragging?.id === device.id ? "dragging" : ""}`}
              style={{
                left: origin.x + at.x * scale,
                top: origin.y + at.y * scale,
                width: device.width * scale,
                height: device.height * scale,
              }}
              onPointerDown={(e) =>
                startDrag(e, device, position(device, screen))
              }
              title="Arraste para outro lado ou posição"
            >
              <span>{device.name}</span>
            </div>
          );
        })}
        {approved.length === 0 && (
          <p className="screens-empty">Nenhuma tela aprovada ainda.</p>
        )}
      </div>

      {loose.length > 0 && (
        <div className="screens-loose">
          <span className="helper !m-0">Arraste para perto do PC:</span>
          {loose.map((device) => (
            <div
              key={device.id}
              className={`screen-chip ${device.online ? "online" : ""}`}
              onPointerDown={(e) =>
                startDrag(e, device, {
                  // The device starts centered under the pointer, in PC pixels.
                  x:
                    (e.clientX -
                      (area.current?.getBoundingClientRect().left ?? 0) -
                      origin.x) /
                      scale -
                    device.width / 2,
                  y:
                    (e.clientY -
                      (area.current?.getBoundingClientRect().top ?? 0) -
                      origin.y) /
                      scale -
                    device.height / 2,
                })
              }
            >
              {device.name}
            </div>
          ))}
        </div>
      )}

      {approved.length > 0 && (
        <ul className="screens-list">
          {approved.map((device) => (
            <li key={device.id}>
              <i className={`status-dot ${device.online ? "" : "offline"}`} />
              {editing === device.id ? (
                <form
                  className="grow"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const name = (
                      e.currentTarget.elements.namedItem(
                        "name",
                      ) as HTMLInputElement
                    ).value;
                    setEditing(null);
                    void run(change(device.id, "PATCH", { name }));
                  }}
                >
                  <input
                    name="name"
                    className="field !h-7 !text-xs"
                    defaultValue={device.name}
                    maxLength={40}
                    autoFocus
                    onBlur={(e) => e.currentTarget.form?.requestSubmit()}
                  />
                </form>
              ) : (
                <span className="grow">
                  {device.name}
                  <small>
                    {device.online ? "conectada" : "desconectada"} ·{" "}
                    {device.side
                      ? {
                          left: "à esquerda",
                          right: "à direita",
                          top: "acima",
                          bottom: "abaixo",
                        }[device.side]
                      : "fora do layout"}
                  </small>
                </span>
              )}
              <button
                className="screen-action"
                aria-label={`Renomear ${device.name}`}
                onClick={() => setEditing(device.id)}
              >
                <Pencil size={12} />
              </button>
              {device.side && (
                <button
                  className="screen-action"
                  onClick={() =>
                    void run(change(device.id, "PATCH", { side: null }))
                  }
                >
                  Tirar do layout
                </button>
              )}
              <button
                className="screen-action"
                aria-label={`Remover ${device.name}`}
                onClick={() =>
                  void run(change(device.id, "DELETE"), "Tela removida.")
                }
              >
                <Trash2 size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
