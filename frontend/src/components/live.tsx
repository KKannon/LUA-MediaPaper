import { useEffect, useRef, useState } from "react";
import { Play, ImageOff } from "lucide-react";
import type { Media, Preferences } from "@/lib/storage";
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
  const [blocked, setBlocked] = useState(false);
  const display = useRef<HTMLElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  useScreenWakeLock(preferences.keepAwake);
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    setFailed(false);
    setBlocked(false);
  }, [media.url]);
  useEffect(() => {
    if (!video.current) return;
    if (preferences.autoplay)
      void video.current
        .play()
        .then(() => setBlocked(false))
        .catch(() => setBlocked(true));
    else video.current.pause();
  }, [media.url, preferences.autoplay, preferences.muted]);
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
          muted={preferences.muted}
          playsInline
          autoPlay={preferences.autoplay}
          style={style}
          onError={() => setFailed(true)}
          onPlaying={() => setBlocked(false)}
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
      {blocked && !failed && (
        <button
          className="live-play"
          aria-label="Reproduzir wallpaper"
          onClick={() =>
            void video.current
              ?.play()
              .then(() => setBlocked(false))
              .catch(() => setBlocked(true))
          }
        >
          <Play size={22} />
          <span>Toque para reproduzir</span>
        </button>
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
