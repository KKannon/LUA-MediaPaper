import { useEffect, useRef, useState } from "react";
import { ImageOff, Volume1, Volume2, VolumeX } from "lucide-react";
import { useStored, type Media, type Preferences } from "@/lib/storage";
import type { Weather } from "@/lib/use-weather";
import { useScreenWakeLock } from "@/lib/use-screen-wake-lock";

export function Live({
  media,
  preferences,
  weather = null,
  interactive = true,
}: {
  media: Media;
  preferences: Preferences;
  weather?: Weather | null;
  /** F, Esc and double click toggle fullscreen only while the wallpaper is in front. */
  interactive?: boolean;
}) {
  const [now, setNow] = useState(new Date());
  const [failed, setFailed] = useState(false);
  // Sound is chosen on each device and remembered there; the shared "Silenciar vídeos" is only the default.
  const [sound, setSound] = useStored<{
    muted: boolean;
    volume: number;
  } | null>("lua:sound", null);
  const muted = sound ? sound.muted : preferences.muted;
  const volume = sound?.volume ?? 0.8;
  const [silenced, setSilenced] = useState(false); // The browser refused sound until a tap.
  const [panel, setPanel] = useState(false);
  const display = useRef<HTMLElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  useScreenWakeLock(preferences.keepAwake);
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    setFailed(false);
  }, [media.url]);
  // The video always plays: with sound if allowed, muted if not, and on the first tap if even that is refused.
  useEffect(() => {
    const element = video.current;
    if (!element) return;
    element.volume = volume;
    element.muted = muted;
    let retry: (() => void) | null = null;
    element
      .play()
      .then(() => setSilenced(false))
      .catch(() => {
        element.muted = true;
        setSilenced(!muted);
        // The first real tap anywhere (even the drag to unlock) restores the saved sound.
        retry = () => {
          element.muted = muted;
          void element
            .play()
            .then(() => setSilenced(false))
            .catch(() => {});
        };
        window.addEventListener("pointerdown", retry, {
          once: true,
          capture: true,
        });
        return element.play().catch(() => {});
      });
    return () => {
      if (retry)
        window.removeEventListener("pointerdown", retry, { capture: true });
    };
  }, [media.url, muted, volume]);
  function changeSound(next: { muted: boolean; volume: number }) {
    setSound(next);
    const element = video.current;
    if (!element) return;
    // Applied right away inside the tap, which is what browsers require to allow sound.
    element.volume = next.volume;
    element.muted = next.muted;
    void element.play().catch(() => {});
    setSilenced(false);
  }
  async function fullscreen() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await display.current?.requestFullscreen();
    } catch {
      /* The route always fills the viewport. */
    }
  }
  useEffect(() => {
    if (!interactive) return;
    const key = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "f") {
        event.preventDefault();
        void fullscreen();
      }
      if (event.key === "Escape" && document.fullscreenElement)
        void document.exitFullscreen().catch(() => {});
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [interactive]);
  const style = {
    objectFit: preferences.fit,
    filter: `brightness(${1 - preferences.dim / 100})`,
  };
  const hour = now.getHours();
  return (
    <main
      ref={display}
      className="live-display"
      aria-label={`Wallpaper ao vivo: ${media.name}`}
      onDoubleClick={() => interactive && void fullscreen()}
    >
      {media.type === "video" ? (
        <video
          ref={video}
          key={media.url}
          src={media.url}
          loop
          muted
          playsInline
          autoPlay
          style={style}
          onError={() => setFailed(true)}
        />
      ) : (
        <img
          src={media.url}
          alt={media.name}
          style={style}
          onError={() => setFailed(true)}
        />
      )}
      <div className="live-shade" />
      <div className="stage-clock">
        {preferences.date && (
          <div className="date">
            {now.toLocaleDateString("pt-BR", {
              weekday: "long",
              day: "numeric",
              month: "long",
            })}
          </div>
        )}
        {preferences.clock && (
          <>
            <div className="time">
              {now.toLocaleTimeString("pt-BR", {
                hour: "2-digit",
                minute: "2-digit",
                hour12: !preferences.hour24,
              })}
            </div>
            <div className="greeting">
              {hour < 12 ? "Bom dia." : hour < 18 ? "Boa tarde." : "Boa noite."}{" "}
              Respire. Este momento é seu.
            </div>
          </>
        )}
        {weather && (
          <div className="live-weather">
            <strong>{weather.temperature}°</strong>
            <span>
              {weather.city}
              {weather.description && ` · ${weather.description}`}
            </span>
          </div>
        )}
      </div>
      {media.type === "video" && !failed && (
        <div
          className={`live-sound ${panel ? "open" : ""}`}
          onPointerDown={(e) => e.stopPropagation()}
          onDoubleClick={(e) => e.stopPropagation()}
        >
          {panel && (
            <input
              type="range"
              min={0}
              max={100}
              value={muted ? 0 : Math.round(volume * 100)}
              aria-label="Volume do vídeo"
              onChange={(e) => {
                const value = Number(e.target.value) / 100;
                changeSound({ muted: value === 0, volume: value || volume });
              }}
            />
          )}
          <button
            aria-label={muted || silenced ? "Ativar som" : "Volume"}
            title={
              silenced ? "Toque para ativar o som" : "Volume deste aparelho"
            }
            className={silenced ? "pulse" : ""}
            onClick={() => {
              if (muted || silenced) {
                changeSound({ muted: false, volume: volume || 0.8 });
                setPanel(true);
              } else setPanel((open) => !open);
            }}
            onContextMenu={(e) => {
              e.preventDefault();
              changeSound({ muted: !muted, volume });
            }}
          >
            {muted || silenced ? (
              <VolumeX size={18} />
            ) : volume < 0.5 ? (
              <Volume1 size={18} />
            ) : (
              <Volume2 size={18} />
            )}
          </button>
          {panel && (
            <button
              className="live-mute"
              onClick={() => changeSound({ muted: !muted, volume })}
            >
              {muted ? "Ativar som" : "Silenciar"}
            </button>
          )}
        </div>
      )}
      {failed && (
        <div className="live-unavailable" role="status">
          <ImageOff size={28} />
          <span>Esta mídia está indisponível.</span>
        </div>
      )}
    </main>
  );
}
