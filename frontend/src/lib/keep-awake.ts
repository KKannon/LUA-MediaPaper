/**
 * Keeps the device screen on. The Screen Wake Lock API needs HTTPS or localhost; on a plain
 * http:// network address a tiny muted looping video does the job (the NoSleep technique).
 * Browsers only allow starting it from a tap or click.
 */
let video: HTMLVideoElement | null = null;

export async function keepAwake() {
  if (window.isSecureContext && "wakeLock" in navigator) return;
  if (!video) {
    video = document.createElement("video");
    video.src = "/wallpapers/keep-awake.mp4";
    video.muted = true;
    video.loop = true;
    video.playsInline = true;
    video.setAttribute("playsinline", "");
    video.setAttribute("aria-hidden", "true");
    Object.assign(video.style, {
      position: "fixed",
      width: "1px",
      height: "1px",
      opacity: "0.01",
      pointerEvents: "none",
      left: "0",
      bottom: "0",
    });
    document.body.appendChild(video);
  }
  try {
    await video.play();
  } catch {
    /* Retried on the next tap. */
  }
}

export function canFullscreen() {
  return !!document.fullscreenEnabled;
}
