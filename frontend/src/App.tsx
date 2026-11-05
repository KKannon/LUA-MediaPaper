import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  FileCheck2,
  FileText,
  Film,
  Focus,
  Grid2X2,
  House,
  Image as ImageIcon,
  Laptop,
  Link2,
  LoaderCircle,
  Maximize,
  Minimize,
  Monitor,
  Moon,
  Pause,
  Play,
  Plus,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Trash2,
  Upload,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { Toaster, toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Live } from "@/components/live";
import { MonitorOS } from "@/components/monitor";
import { ScreensPanel } from "@/components/screens";
import { useWallpaper } from "@/lib/use-wallpaper";
import { useYouTube, isYouTube } from "@/lib/use-youtube";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  csrf,
  defaultPreferences,
  presets,
  useStored,
  type Media,
  type Preferences,
} from "@/lib/storage";

type Status = {
  desktop: boolean;
  startup: boolean;
  version: string;
  networkUrls?: string[];
};
type OptionProps = {
  id: string;
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  icon?: React.ReactNode;
  description?: string;
  disabled?: boolean;
};
function Toggle({
  id,
  label,
  checked,
  onChange,
  icon,
  description,
  disabled,
}: OptionProps) {
  return (
    <div className="option-row">
      <div>
        <label htmlFor={id}>
          {icon}
          {label}
        </label>
        {description && <p className="setting-description">{description}</p>}
      </div>
      <Switch
        id={id}
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
      />
    </div>
  );
}

export default function App() {
  const location = useLocation();
  const live = /^\/live\/?$/.test(location.pathname);
  const monitor = /^\/monitor\/?$/.test(location.pathname);
  const { media, setMedia, preferences, setPreferences } = useWallpaper(
    live || monitor,
  );
  const [library, setLibrary] = useStored<Media[]>("lua:library", []);
  const [status, setStatus] = useState<Status | null>(null);
  const [online, setOnline] = useState(false);
  useEffect(() => {
    fetch("/api/status")
      .then((r) => {
        if (!r.ok) throw Error();
        return r.json();
      })
      .then((s) => {
        setStatus(s);
        setOnline(true);
      })
      .catch(() => setOnline(false));
  }, []);
  useEffect(() => {
    document.title = `${live ? "Ao vivo" : monitor ? "Lua OS" : location.pathname.startsWith("/definicoes") ? "Definições" : location.pathname.startsWith("/mais/epub-pdf") ? "EPUB para PDF" : location.pathname.startsWith("/mais/pdf-epub") ? "PDF para EPUB" : location.pathname.startsWith("/mais") ? "Mais ferramentas" : "Home"} · Lua MediaPaper`;
  }, [location.pathname]);
  const updatePreference = <K extends keyof Preferences>(
    key: K,
    value: Preferences[K],
  ) => setPreferences((previous) => ({ ...previous, [key]: value }));
  if (live) return <Live media={media} preferences={preferences} />;
  if (monitor) return <MonitorOS media={media} preferences={preferences} />;
  return (
    <>
      <header className="app-nav">
        <Link to="/" className="brand" aria-label="Lua MediaPaper — Home">
          <span className="brand-mark">
            <Moon size={20} strokeWidth={1.5} />
          </span>
          <strong>
            Lua <span>MediaPaper</span>
          </strong>
        </Link>
        <nav className="nav-links" aria-label="Navegação principal">
          <NavLink to="/" end>
            <House size={15} />
            Home
          </NavLink>
          <NavLink to="/definicoes">
            <Settings2 size={15} />
            Definições
          </NavLink>
          <NavLink to="/mais">
            <Grid2X2 size={15} />
            Mais
          </NavLink>
        </nav>
        <div className="nav-status">
          <i
            className="status-dot"
            style={online ? undefined : { background: "#deaa68" }}
          />
          <span>
            {online
              ? status?.desktop
                ? "Aplicativo conectado"
                : "Servidor conectado"
              : "Conectando ao servidor"}
          </span>
          <div className="avatar">LM</div>
        </div>
      </header>
      <Routes>
        <Route
          path="/"
          element={
            <Home
              media={media}
              setMedia={setMedia}
              library={library}
              setLibrary={setLibrary}
              preferences={preferences}
              updatePreference={updatePreference}
            />
          }
        />
        <Route
          path="/home"
          element={
            <Home
              media={media}
              setMedia={setMedia}
              library={library}
              setLibrary={setLibrary}
              preferences={preferences}
              updatePreference={updatePreference}
            />
          }
        />
        <Route
          path="/definicoes"
          element={
            <Settings
              preferences={preferences}
              updatePreference={updatePreference}
              status={status}
              setStatus={setStatus}
              reset={() => {
                setMedia(presets[0]);
                setPreferences(defaultPreferences);
                toast.success("Preferências restauradas.");
              }}
            />
          }
        />
        <Route path="/mais" element={<Tools />} />
        <Route path="/mais/epub-pdf" element={<Converter kind="epub-pdf" />} />
        <Route path="/mais/pdf-epub" element={<Converter kind="pdf-epub" />} />
        <Route
          path="*"
          element={
            <main className="page">
              <h1>Página não encontrada</h1>
              <Link to="/">Voltar para Home</Link>
            </main>
          }
        />
      </Routes>
      <Toaster theme="dark" position="bottom-right" richColors closeButton />
    </>
  );
}

type HomeProps = {
  media: Media;
  setMedia: (m: Media) => void;
  library: Media[];
  setLibrary: (m: Media[] | ((old: Media[]) => Media[])) => void;
  preferences: Preferences;
  updatePreference: <K extends keyof Preferences>(
    k: K,
    v: Preferences[K],
  ) => void;
};
function Home({
  media,
  setMedia,
  library,
  setLibrary,
  preferences,
  updatePreference,
}: HomeProps) {
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState<"auto" | Media["type"]>("auto");
  const [filter, setFilter] = useState<"all" | Media["type"]>("all");
  const [fullscreen, setFullscreen] = useState(false);
  const [error, setError] = useState(false);
  const [now, setNow] = useState(new Date());
  const [paused, setPaused] = useState(!preferences.autoplay);
  const [dialog, setDialog] = useState(false);
  const youtube = useYouTube();
  const savedYouTubeJob = useRef<string | undefined>(undefined);
  useEffect(() => {
    const job = youtube.job;
    if (
      !job.id ||
      job.id !== youtube.initiated.current ||
      savedYouTubeJob.current === job.id
    )
      return;
    if (job.status === "ready" && job.media?.sourceUrl) {
      savedYouTubeJob.current = job.id;
      const entry = { ...job.media, url: job.media.sourceUrl };
      setLibrary((old) =>
        [entry, ...old.filter((item) => item.id !== entry.id)].slice(0, 20),
      );
      toast.success("Vídeo do YouTube pronto e aplicado.");
    } else if (job.status === "error") {
      savedYouTubeJob.current = job.id;
      toast.error(job.message || "Não foi possível baixar o vídeo.");
    }
  }, [youtube.job, setLibrary]);
  const stage = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const urlInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    setError(false);
  }, [media.url]);
  useEffect(() => {
    if (!video.current) return;
    if (preferences.autoplay)
      video.current
        .play()
        .then(() => setPaused(false))
        .catch(() => setPaused(true));
    else {
      video.current.pause();
      setPaused(true);
    }
  }, [media.url, preferences.autoplay]);
  useEffect(() => {
    const change = () => {
      if (!document.fullscreenElement) setFullscreen(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (document.fullscreenElement)
          void document.exitFullscreen().catch(() => {});
        setFullscreen(false);
      }
      if (
        e.key.toLowerCase() === "f" &&
        !["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(
          (e.target as HTMLElement).tagName,
        ) &&
        !dialog
      ) {
        e.preventDefault();
        void enterFullscreen();
      }
    };
    document.addEventListener("fullscreenchange", change);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("fullscreenchange", change);
      document.removeEventListener("keydown", key);
    };
  }, [fullscreen, dialog]);
  async function enterFullscreen() {
    if (fullscreen) {
      if (document.fullscreenElement) await document.exitFullscreen();
      setFullscreen(false);
      return;
    }
    setFullscreen(true);
    try {
      await stage.current?.requestFullscreen();
    } catch {
      /* CSS fullscreen is supported when the browser API is unavailable. */
    }
  }
  function apply(event?: FormEvent) {
    event?.preventDefault();
    let parsed: URL;
    try {
      parsed = new URL(url.trim());
      if (
        !["https:", "http:"].includes(parsed.protocol) ||
        parsed.username ||
        parsed.password
      )
        throw Error();
    } catch {
      toast.error("Informe um link válido começando com https:// ou http://.");
      return;
    }
    if (isYouTube(parsed.href)) {
      void youtube.start(parsed.href).then((started) => {
        if (started) {
          setDialog(false);
          setUrl("");
        }
      });
      return;
    }
    if (/(^|\.)vimeo\.com$/.test(parsed.hostname)) {
      toast.error(
        "Use o link direto do arquivo, como .mp4 ou .webm. Links de páginas de vídeo não são compatíveis.",
      );
      return;
    }
    const type =
      kind === "auto"
        ? /\.(mp4|webm|ogg|mov)$/i.test(parsed.pathname)
          ? "video"
          : /\.gif$/i.test(parsed.pathname)
            ? "gif"
            : "image"
        : kind;
    const entry: Media = {
      id: crypto.randomUUID(),
      url: parsed.href,
      type,
      name: "Meu wallpaper",
      description: parsed.hostname,
    };
    setMedia(entry);
    setLibrary((old) =>
      [entry, ...old.filter((m) => m.url !== entry.url)].slice(0, 20),
    );
    setDialog(false);
    setUrl("");
    toast.success("Wallpaper aplicado e salvo na sua coleção.");
  }
  const items = [...presets, ...library].filter(
    (m) => filter === "all" || m.type === filter,
  );
  const hour = now.getHours();
  const sourceForm = (
    <form onSubmit={apply}>
      <label
        className="label"
        htmlFor={dialog ? "dialog-url" : "wallpaper-url"}
      >
        Link da mídia
      </label>
      <div className="input-icon">
        <Link2 size={13} />
        <input
          ref={urlInput}
          id={dialog ? "dialog-url" : "wallpaper-url"}
          className="field"
          placeholder="https://exemplo.com/imagem.jpg"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
          type="url"
        />
      </div>
      <p className="helper">
        Foto, vídeo, GIF ou YouTube de até 20 min. YouTube é baixado na melhor
        qualidade, até 4K.
      </p>
      <div className="type-picker" aria-label="Tipo de mídia">
        {(
          [
            ["auto", "Auto", Sparkles],
            ["image", "Foto", ImageIcon],
            ["video", "Vídeo", Film],
            ["gif", "GIF", Focus],
          ] as const
        ).map(([value, label, Icon]) => (
          <button
            type="button"
            key={value}
            aria-pressed={kind === value}
            className={kind === value ? "selected" : ""}
            onClick={() => setKind(value)}
          >
            <Icon size={11} />
            {label}
          </button>
        ))}
      </div>
      <Button
        type="submit"
        className="w-full h-9 text-xs gap-2"
        disabled={youtube.busy && isYouTube(url)}
      >
        {youtube.starting ? (
          <LoaderCircle size={13} className="spin" />
        ) : (
          <Check size={13} />
        )}
        {isYouTube(url) ? "Baixar e aplicar YouTube" : "Aplicar wallpaper"}
      </Button>
    </form>
  );
  return (
    <main className="page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <span className="status-dot" />
            SEU ESPAÇO, NO SEU RITMO
          </div>
          <h1>Um novo olhar para sua tela.</h1>
          <p className="subtitle">
            Transforme o fundo em algo que combina com você.
          </p>
        </div>
        <div className="heading-actions">
          <Dialog open={dialog} onOpenChange={setDialog}>
            <DialogTrigger asChild>
              <Button variant="outline" className="h-9 text-xs gap-2">
                <Plus size={14} />
                Adicionar mídia
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle>Um wallpaper com a sua cara.</DialogTitle>
                <DialogDescription>
                  Use um link direto para adicionar uma foto, vídeo ou GIF à sua
                  coleção.
                </DialogDescription>
              </DialogHeader>
              <div className="py-3">{dialog && sourceForm}</div>
            </DialogContent>
          </Dialog>
          <Button asChild className="h-9 text-xs gap-2">
            <Link to="/live" target="_blank" rel="noopener">
              <Maximize size={14} />
              Abrir /live
            </Link>
          </Button>
        </div>
      </div>
      <div className="home-grid">
        <div>
          <div ref={stage} className={fullscreen ? "fullscreen" : ""}>
            <div
              className="wallpaper-stage"
              aria-label={`Wallpaper: ${media.name}`}
            >
              {media.type === "video" ? (
                <video
                  key={media.url}
                  ref={video}
                  src={media.url}
                  loop
                  muted={preferences.muted}
                  playsInline
                  autoPlay={preferences.autoplay}
                  onError={() => setError(true)}
                  onPlay={() => setPaused(false)}
                  onPause={() => setPaused(true)}
                  style={{
                    objectFit: preferences.fit,
                    filter: `brightness(${1 - preferences.dim / 100})`,
                  }}
                />
              ) : (
                <img
                  src={media.url}
                  alt={media.name}
                  onError={() => setError(true)}
                  style={{
                    objectFit: preferences.fit,
                    filter: `brightness(${1 - preferences.dim / 100})`,
                  }}
                />
              )}
              {!fullscreen && (
                <div className="stage-top">
                  <span className="glass-badge">
                    <span className="status-dot" />
                    {fullscreen ? "SEU MOMENTO" : "PRÉVIA DO WALLPAPER"}
                  </span>
                  <button
                    className="stage-control"
                    title={
                      fullscreen ? "Sair da tela cheia" : "Abrir em tela cheia"
                    }
                    aria-label={
                      fullscreen ? "Sair da tela cheia" : "Abrir em tela cheia"
                    }
                    onClick={() => void enterFullscreen()}
                  >
                    {fullscreen ? (
                      <Minimize size={14} />
                    ) : (
                      <Maximize size={14} />
                    )}
                  </button>
                </div>
              )}
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
                      {hour < 12
                        ? "Bom dia."
                        : hour < 18
                          ? "Boa tarde."
                          : "Boa noite."}{" "}
                      Respire. Este momento é seu.
                    </div>
                  </>
                )}
              </div>
              {!fullscreen && (
                <div className="stage-bottom">
                  <div className="stage-caption">
                    <strong>{media.name}</strong>
                    <p>{media.description}</p>
                  </div>
                  <div className="flex gap-2">
                    {media.type === "video" && (
                      <>
                        <button
                          className="stage-control"
                          aria-label={
                            paused ? "Reproduzir vídeo" : "Pausar vídeo"
                          }
                          onClick={() => {
                            if (paused)
                              video.current
                                ?.play()
                                .catch(() =>
                                  toast.error(
                                    "Não foi possível reproduzir o vídeo.",
                                  ),
                                );
                            else video.current?.pause();
                          }}
                        >
                          {paused ? <Play size={13} /> : <Pause size={13} />}
                        </button>
                        <button
                          className="stage-control"
                          aria-label={
                            preferences.muted ? "Ativar som" : "Silenciar"
                          }
                          onClick={() =>
                            updatePreference("muted", !preferences.muted)
                          }
                        >
                          {preferences.muted ? (
                            <VolumeX size={13} />
                          ) : (
                            <Volume2 size={13} />
                          )}
                        </button>
                      </>
                    )}
                    <span className="glass-badge">
                      {media.type === "video"
                        ? "VÍDEO"
                        : media.type === "gif"
                          ? "GIF"
                          : "FOTOGRAFIA"}
                    </span>
                  </div>
                </div>
              )}
              {error && (
                <div className="media-error">
                  <ImageIcon size={30} />
                  <strong>Não foi possível carregar esta mídia.</strong>
                  <p>
                    Verifique se o link aponta diretamente para um arquivo
                    acessível. O servidor de origem pode bloquear sua exibição.
                  </p>
                  <Button
                    variant="outline"
                    onClick={() => setMedia(presets[0])}
                  >
                    Voltar ao wallpaper inicial
                  </Button>
                </div>
              )}
            </div>
          </div>
          <div className="preview-footer">
            <span className="flex items-center gap-1.5">
              <Monitor size={11} />
              Prévia em tempo real
            </span>
            <span>
              Pressione <kbd>F</kbd> para tela cheia · <kbd>Esc</kbd> para sair
            </span>
          </div>
        </div>
        <aside className="sidebar">
          <section className="panel">
            <h2 className="panel-heading">
              <Link2 />
              Seu wallpaper
            </h2>
            {!dialog && sourceForm}
            {youtube.job.status !== "idle" && (
              <div className="youtube-progress" role="status">
                <div className="flex items-center gap-2 text-[11px]">
                  {youtube.busy ? (
                    <LoaderCircle size={13} className="spin text-primary" />
                  ) : youtube.job.status === "ready" ? (
                    <Check size={13} className="text-primary" />
                  ) : (
                    <Film size={13} />
                  )}
                  <span>{youtube.job.title || "YouTube"}</span>
                </div>
                <p className="helper !mb-2">{youtube.job.message}</p>
                {youtube.job.status === "downloading" && (
                  <progress
                    aria-label="Progresso do download"
                    max={100}
                    value={youtube.job.progress ?? undefined}
                    className="w-full h-1 accent-[#c1e697]"
                  />
                )}
                {youtube.busy && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="w-full text-[10px]"
                    onClick={() => void youtube.cancel()}
                  >
                    Cancelar download
                  </Button>
                )}
              </div>
            )}
          </section>
          <section className="panel">
            <h2 className="panel-heading">
              <SlidersHorizontal />
              Do seu jeito
            </h2>
            <div className="option-row">
              <label htmlFor="fit">
                <Maximize />
                Enquadramento
              </label>
              <select
                id="fit"
                className="select-small"
                value={preferences.fit}
                onChange={(e) =>
                  updatePreference("fit", e.target.value as Preferences["fit"])
                }
              >
                <option value="cover">Preencher</option>
                <option value="contain">Ajustar</option>
              </select>
            </div>
            <Toggle
              id="show-clock"
              label="Mostrar relógio"
              icon={<Clock3 />}
              checked={preferences.clock}
              onChange={(v) => updatePreference("clock", v)}
            />
            <Toggle
              id="show-date"
              label="Mostrar data"
              icon={<Sun />}
              checked={preferences.date}
              onChange={(v) => updatePreference("date", v)}
            />
            <Toggle
              id="mute-video"
              label="Silenciar vídeos"
              icon={<VolumeX />}
              checked={preferences.muted}
              onChange={(v) => updatePreference("muted", v)}
            />
            <div className="separator" />
            <Link
              to="/definicoes"
              className="flex items-center justify-between text-[10px] text-muted-foreground hover:text-primary"
            >
              Todas as definições
              <ChevronRight size={12} />
            </Link>
          </section>
          <section className="panel tip-panel">
            <div className="flex items-center gap-2 text-[11px] text-primary">
              <Sparkles size={13} />
              Menos distração, mais presença.
            </div>
            <p>
              Ative a tela cheia e deixe o resto para depois. Seu espaço merece
              uma pausa.
            </p>
          </section>
        </aside>
      </div>
      <section className="collection">
        <div className="section-heading">
          <h2>
            Um pouco de inspiração<span>Sua próxima vista favorita.</span>
          </h2>
          <div className="filter-chips" aria-label="Filtrar coleção">
            {(
              [
                ["all", "Todos"],
                ["image", "Fotos"],
                ["video", "Vídeos"],
                ["gif", "GIFs"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                className={filter === value ? "selected" : ""}
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="collection-grid">
          {items.map((item) => (
            <div key={item.id} className="relative">
              <button
                className={`wallpaper-card w-full ${media.id === item.id ? "selected" : ""}`}
                onClick={() => {
                  if (isYouTube(item.sourceUrl || item.url))
                    void youtube.start(item.sourceUrl || item.url);
                  else {
                    setMedia(item);
                    toast.success(`Wallpaper “${item.name}” aplicado.`);
                  }
                }}
                aria-label={`Aplicar ${item.name}`}
                aria-pressed={media.id === item.id}
              >
                <div className="thumb">
                  {item.thumbnail ? (
                    <img src={item.thumbnail} alt="" loading="lazy" />
                  ) : item.type === "video" ? (
                    <video src={item.url} muted preload="metadata" />
                  ) : (
                    <img src={item.url} alt="" loading="lazy" />
                  )}
                  <span className="thumb-type">
                    {item.type === "video"
                      ? "VÍDEO"
                      : item.type === "gif"
                        ? "GIF"
                        : "FOTO"}
                  </span>
                  {media.id === item.id && (
                    <Check size={18} className="check" />
                  )}
                </div>
                <div className="card-title">
                  <span>{item.name}</span>
                  {presets.some((p) => p.id === item.id) && (
                    <small>Lua collection</small>
                  )}
                </div>
                <div className="card-description">{item.description}</div>
              </button>
              {!presets.some((p) => p.id === item.id) && (
                <button
                  className="absolute top-2 right-2 rounded bg-black/60 p-1.5 text-white"
                  aria-label={`Remover ${item.name} da coleção`}
                  onClick={() => {
                    setLibrary((old) => old.filter((m) => m.id !== item.id));
                    if (media.id === item.id) setMedia(presets[0]);
                    toast.success("Mídia removida da coleção.");
                  }}
                >
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          ))}
          {items.length === 0 && (
            <div className="empty-filter">
              Sua coleção de {filter === "video" ? "vídeos" : "GIFs"} começa
              aqui. Adicione o link de uma mídia para vê-la neste espaço.
            </div>
          )}
        </div>
      </section>
      <ScreensPanel />
      <Footer />
    </main>
  );
}

function Settings({
  preferences,
  updatePreference,
  status,
  setStatus,
  reset,
}: {
  preferences: Preferences;
  updatePreference: HomeProps["updatePreference"];
  status: Status | null;
  setStatus: (s: Status) => void;
  reset: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  async function startup(enabled: boolean) {
    setBusy(true);
    try {
      const r = await fetch("/api/startup", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ enabled }),
      });
      const body = await r.json();
      if (!r.ok) throw Error(body.error);
      if (status) setStatus({ ...status, startup: body.startup });
      toast.success(
        enabled
          ? "Inicialização com o Windows ativada."
          : "Inicialização com o Windows desativada.",
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Não foi possível salvar.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="page content-narrow">
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <Settings2 size={12} />
            OS PEQUENOS DETALHES
          </div>
          <h1>Um espaço que é seu.</h1>
          <p className="subtitle">
            Ajuste a experiência para combinar com o seu ritmo.
          </p>
        </div>
      </div>
      <div className="settings-grid">
        <section className="panel">
          <h2>Na sua tela</h2>
          <p className="subtitle text-xs">O que aparece sobre o wallpaper.</p>
          <Toggle
            id="setting-clock"
            label="Mostrar relógio"
            checked={preferences.clock}
            onChange={(v) => updatePreference("clock", v)}
          />
          <Toggle
            id="setting-date"
            label="Mostrar data"
            checked={preferences.date}
            onChange={(v) => updatePreference("date", v)}
          />
          <Toggle
            id="setting-hour24"
            label="Formato de 24 horas"
            checked={preferences.hour24}
            onChange={(v) => updatePreference("hour24", v)}
          />
          <Toggle
            id="setting-awake"
            label="Manter tela ligada no /live"
            checked={preferences.keepAwake}
            onChange={(v) => updatePreference("keepAwake", v)}
            description="Mantém a tela ativa enquanto o /live estiver visível. Requer navegador compatível e HTTPS ou localhost."
          />
          <div className="option-row">
            <label htmlFor="setting-fit">Enquadramento</label>
            <select
              id="setting-fit"
              className="select-small"
              value={preferences.fit}
              onChange={(e) =>
                updatePreference("fit", e.target.value as Preferences["fit"])
              }
            >
              <option value="cover">Preencher a tela</option>
              <option value="contain">Ajustar à tela</option>
            </select>
          </div>
          <div className="mt-4">
            <label htmlFor="dim" className="label flex justify-between">
              <span>Escurecer wallpaper</span>
              <span>{preferences.dim}%</span>
            </label>
            <input
              id="dim"
              type="range"
              min="0"
              max="70"
              step="5"
              value={preferences.dim}
              onChange={(e) => updatePreference("dim", Number(e.target.value))}
              className="w-full accent-[#c1e697]"
            />
          </div>
        </section>
        <section className="panel">
          <h2>Movimento e som</h2>
          <p className="subtitle text-xs">Vídeos do seu jeito.</p>
          <Toggle
            id="setting-muted"
            label="Silenciar vídeos"
            checked={preferences.muted}
            onChange={(v) => updatePreference("muted", v)}
            description="Comece com o som desligado. Você pode ativá-lo na prévia."
          />
          <Toggle
            id="setting-autoplay"
            label="Reproduzir automaticamente"
            checked={preferences.autoplay}
            onChange={(v) => updatePreference("autoplay", v)}
            description="Vídeos são repetidos continuamente. Alguns navegadores exigem uma interação para reproduzir com som."
          />
          <p className="helper">GIFs seguem a animação do arquivo original.</p>
        </section>
        <section className="panel">
          <div className="flex justify-between items-center mb-3">
            <h2>Aplicativo e sistema</h2>
            <span className="pill">
              <Laptop size={11} />
              {status?.desktop ? "Portátil" : "Servidor"}
            </span>
          </div>
          <Toggle
            id="setting-startup"
            label="Iniciar com o Windows"
            checked={status?.startup || false}
            onChange={(v) => void startup(v)}
            disabled={!status?.desktop || busy}
            description={
              status?.desktop
                ? "O Lua inicia na bandeja, sem abrir o navegador."
                : "Disponível ao abrir o executável portátil no Windows."
            }
          />
          <div className="separator" />
          <p className="setting-description">
            {status?.desktop
              ? "O app continua rodando na bandeja quando você fecha o navegador. Use o ícone da Lua para abrir ou encerrar."
              : "No modo servidor, acesse o mesmo endereço em qualquer dispositivo autorizado na sua rede."}
          </p>
          <div className="separator" />
          <p className="setting-description">
            {status?.networkUrls?.length ? (
              <>
                Outros dispositivos na mesma rede podem abrir{" "}
                {status.networkUrls.map((url, index) => (
                  <span key={url}>
                    {index > 0 && " ou "}
                    <a href={url + "live"} className="underline">
                      {url + "live"}
                    </a>
                  </span>
                ))}
                . Se o Windows perguntar, permita o acesso na rede privada.
              </>
            ) : (
              "Acesso pela rede indisponível: o app está ouvindo apenas neste computador ou não há rede conectada."
            )}
          </p>
        </section>
        <section className="panel">
          <h2>Seu espaço, salvo.</h2>
          <p className="setting-description">
            O wallpaper e as preferências ficam salvos no servidor e
            sincronizados com o /live. Sua coleção de links continua neste
            navegador. Os livros não entram em uma biblioteca no servidor.
          </p>
          <div className="separator" />
          <Button
            variant="outline"
            className="text-xs"
            onClick={() => setConfirm(true)}
          >
            Restaurar preferências
          </Button>
          <Dialog open={confirm} onOpenChange={setConfirm}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Restaurar as preferências?</DialogTitle>
                <DialogDescription>
                  O wallpaper inicial e as opções de exibição serão restaurados.
                  Sua coleção de links será mantida.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" onClick={() => setConfirm(false)}>
                  Cancelar
                </Button>
                <Button
                  onClick={() => {
                    reset();
                    setConfirm(false);
                  }}
                >
                  Restaurar
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </section>
      </div>
      <Footer />
    </main>
  );
}

function Tools() {
  return (
    <main className="page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <Grid2X2 size={12} />
            ALÉM DO WALLPAPER
          </div>
          <h1>Pequenas ferramentas. Mais possibilidades.</h1>
          <p className="subtitle">
            Escolha o que precisa e deixe o Lua cuidar do resto.
          </p>
        </div>
        <span className="pill">2 ferramentas disponíveis</span>
      </div>
      <div className="tools-grid">
        <Link to="/mais/epub-pdf" className="panel tool-card">
          <div className="flex justify-between items-start">
            <div className="tool-icon">
              <BookOpen size={23} strokeWidth={1.5} />
            </div>
            <span className="pill">DOCUMENTOS</span>
          </div>
          <h2>EPUB para PDF</h2>
          <p>
            Seus livros em um formato que vai com você. Converta arquivos EPUB
            em PDFs prontos para ler ou imprimir.
          </p>
          <span className="tool-link">
            Abrir conversor
            <ArrowRight size={16} />
          </span>
        </Link>
        <Link to="/mais/pdf-epub" className="panel tool-card">
          <div className="flex justify-between items-start">
            <div className="tool-icon">
              <FileText size={23} strokeWidth={1.5} />
            </div>
            <span className="pill">DOCUMENTOS</span>
          </div>
          <h2>PDF para EPUB</h2>
          <p>
            Texto que se ajusta à tela. Transforme PDFs em EPUBs para ler no
            celular, tablet ou leitor digital.
          </p>
          <span className="tool-link">
            Abrir conversor
            <ArrowRight size={16} />
          </span>
        </Link>
      </div>
      <div className="tools-note">
        <Sparkles size={22} className="shrink-0 text-primary" />
        <span>
          Este é só o começo. Novas ferramentas terão um lugar por aqui, sempre
          à sua escolha.
        </span>
      </div>
      <Footer />
    </main>
  );
}

const converters = {
  "epub-pdf": {
    from: "EPUB",
    to: "PDF",
    extension: ".epub",
    accept: ".epub,application/epub+zip",
    endpoint: "/api/convert",
    eyebrow: "BIBLIOTECA SEM LIMITES",
    title: "Seu EPUB, agora em PDF.",
    subtitle:
      "Selecione seu livro. Ajuste os detalhes. Leve a leitura com você.",
  },
  "pdf-epub": {
    from: "PDF",
    to: "EPUB",
    extension: ".pdf",
    accept: ".pdf,application/pdf",
    endpoint: "/api/convert-pdf",
    eyebrow: "LEITURA QUE SE ADAPTA",
    title: "Seu PDF, agora em EPUB.",
    subtitle:
      "Texto que acompanha o tamanho da tela, do celular ao leitor digital.",
  },
} as const;

function Converter({ kind }: { kind: keyof typeof converters }) {
  const config = converters[kind];
  const [file, setFile] = useState<File | null>(null);
  const [pageSize, setPageSize] = useState("A4");
  const [fontSize, setFontSize] = useState("11");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [result, setResult] = useState<{
    url: string;
    name: string;
    size: number;
  } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const active = useRef(true);
  const controller = useRef<AbortController | null>(null);
  const resultRef = useRef<string | null>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      controller.current?.abort();
      if (resultRef.current) URL.revokeObjectURL(resultRef.current);
    };
  }, []);
  function selectFile(value: File | undefined) {
    if (!value) return;
    if (!value.name.toLowerCase().endsWith(config.extension)) {
      toast.error(`Escolha um arquivo com extensão ${config.extension}.`);
      return;
    }
    if (value.size > 30 * 1024 * 1024) {
      toast.error("O arquivo deve ter no máximo 30 MB.");
      return;
    }
    if (resultRef.current) URL.revokeObjectURL(resultRef.current);
    resultRef.current = null;
    setResult(null);
    setFile(value);
  }
  async function convert() {
    if (!file) return;
    setBusy(true);
    controller.current = new AbortController();
    try {
      await fetch("/api/status", { signal: controller.current.signal });
      const data = new FormData();
      data.append("file", file);
      if (kind === "epub-pdf") {
        data.append("pageSize", pageSize);
        data.append("fontSize", fontSize);
      }
      const r = await fetch(config.endpoint, {
        method: "POST",
        headers: { "X-CSRFToken": csrf() },
        body: data,
        signal: controller.current.signal,
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({
          error: "Falha ao converter. Verifique a conexão com o servidor.",
        }));
        throw Error(body.error);
      }
      const blob = await r.blob();
      if (!active.current) return;
      const url = URL.createObjectURL(blob);
      resultRef.current = url;
      setResult({
        url,
        name: file.name.replace(/\.[^.]+$/, "") + "." + config.to.toLowerCase(),
        size: blob.size,
      });
      toast.success(`Seu ${config.to} está pronto!`);
    } catch (e) {
      if (active.current)
        toast.error(e instanceof Error ? e.message : "Falha na conversão.");
    } finally {
      if (active.current) setBusy(false);
    }
  }
  return (
    <main className="page content-narrow">
      <Link to="/mais" className="back-link">
        <ArrowLeft size={13} />
        Todas as ferramentas
      </Link>
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <BookOpen size={12} />
            {config.eyebrow}
          </div>
          <h1>{config.title}</h1>
          <p className="subtitle">{config.subtitle}</p>
        </div>
      </div>
      <div className="converter-grid">
        <section className="panel">
          <input
            ref={input}
            type="file"
            accept={config.accept}
            className="hidden"
            aria-label={`Selecionar arquivo ${config.from}`}
            onChange={(e) => {
              selectFile(e.target.files?.[0]);
              e.target.value = "";
            }}
            disabled={busy}
          />
          {result ? (
            <div className="conversion-result">
              <FileCheck2
                size={46}
                strokeWidth={1.3}
                className="text-primary mx-auto"
              />
              <h2>Sua próxima leitura está pronta.</h2>
              <p>
                {result.name} · {(result.size / 1024).toFixed(0)} KB
              </p>
              <Button asChild className="gap-2">
                <a href={result.url} download={result.name}>
                  <ArrowDownToLine size={15} />
                  Baixar {config.to}
                </a>
              </Button>
              <Button
                variant="ghost"
                className="mt-4 w-full text-xs"
                onClick={() => {
                  if (resultRef.current) URL.revokeObjectURL(resultRef.current);
                  resultRef.current = null;
                  setResult(null);
                  setFile(null);
                }}
              >
                Converter outro livro
                <ArrowRight size={13} />
              </Button>
            </div>
          ) : file ? (
            <>
              <div className="file-selected">
                <div className="tool-icon !mb-0 shrink-0">
                  <FileText size={22} />
                </div>
                <div className="grow">
                  <strong>{file.name}</strong>
                  <small>
                    {(file.size / 1024 / 1024).toFixed(2)} MB · {config.from}
                  </small>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  disabled={busy}
                  aria-label="Remover arquivo"
                  onClick={() => setFile(null)}
                >
                  <X size={15} />
                </Button>
              </div>
              <div className="min-h-48 flex flex-col justify-center items-center text-center gap-5">
                {busy ? (
                  <>
                    <LoaderCircle size={32} className="spin text-primary" />
                    <div role="status">
                      <p className="text-sm">Preparando sua leitura…</p>
                      <p className="helper">
                        Livros maiores podem levar alguns instantes.
                      </p>
                    </div>
                  </>
                ) : (
                  <>
                    <BookOpen size={35} className="text-primary" />
                    <p className="text-xs text-muted-foreground">
                      Tudo certo. Seu livro está pronto para ser convertido.
                    </p>
                    <Button className="gap-2" onClick={() => void convert()}>
                      Converter para {config.to}
                      <ArrowRight size={14} />
                    </Button>
                    <button
                      className="text-[11px] text-muted-foreground hover:text-primary"
                      onClick={() => input.current?.click()}
                    >
                      Escolher outro arquivo
                    </button>
                  </>
                )}
              </div>
            </>
          ) : (
            <div
              className={`dropzone ${dragging ? "dragging" : ""}`}
              role="button"
              tabIndex={0}
              onClick={() => input.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  input.current?.click();
                }
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                selectFile(e.dataTransfer.files[0]);
              }}
            >
              <div className="tool-icon !mb-0">
                <Upload size={23} strokeWidth={1.4} />
              </div>
              <h2>Solte seu livro por aqui.</h2>
              <p>
                Arraste um arquivo {config.from} ou escolha no computador.
                <br />
                Até 30 MB por arquivo.
              </p>
              <span className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-xs text-primary-foreground">
                <Plus size={14} />
                Escolher arquivo
              </span>
            </div>
          )}
          <div className="mt-5 flex gap-2 items-start text-[10px] text-muted-foreground leading-5">
            <ShieldCheck size={14} className="text-primary shrink-0 mt-0.5" />O
            arquivo é processado neste servidor e descartado após a conversão.
            Nenhum serviço de terceiros recebe seu livro.
          </div>
        </section>
        <aside className="sidebar">
          {kind === "epub-pdf" ? (
            <>
              <section className="panel">
                <h2 className="panel-heading">
                  <SlidersHorizontal />
                  Detalhes do PDF
                </h2>
                <label className="label" htmlFor="page-size">
                  Tamanho da página
                </label>
                <select
                  id="page-size"
                  value={pageSize}
                  disabled={busy || !!result}
                  onChange={(e) => setPageSize(e.target.value)}
                  className="field mb-5"
                >
                  <option value="A4">A4 · 210 × 297 mm</option>
                  <option value="LETTER">Carta · 216 × 279 mm</option>
                </select>
                <label className="label" htmlFor="font-size">
                  Tamanho do texto
                </label>
                <select
                  id="font-size"
                  value={fontSize}
                  disabled={busy || !!result}
                  onChange={(e) => setFontSize(e.target.value)}
                  className="field"
                >
                  <option value="10">Pequeno · 10 pt</option>
                  <option value="11">Padrão · 11 pt</option>
                  <option value="12">Confortável · 12 pt</option>
                  <option value="14">Grande · 14 pt</option>
                </select>
                <p className="helper !mb-0">
                  Capítulos na ordem de leitura, com imagens, títulos e páginas
                  numeradas.
                </p>
              </section>
              <section className="panel tip-panel">
                <div className="flex gap-2 items-center text-[11px] text-primary">
                  <CircleHelp size={14} />
                  Antes de converter
                </div>
                <p>
                  Use um EPUB sem DRM. O texto é adaptado para a página; layouts
                  complexos, fontes especiais e tabelas podem mudar.
                </p>
              </section>
            </>
          ) : (
            <>
              <section className="panel">
                <h2 className="panel-heading">
                  <SlidersHorizontal />
                  Como fica o EPUB
                </h2>
                <p className="helper !mb-0">
                  Parágrafos refeitos, palavras hifenizadas reunidas, títulos
                  detectados pelo tamanho da fonte e imagens no lugar. Os
                  capítulos seguem os marcadores do PDF; sem marcadores, o livro
                  é dividido a cada 10 páginas. Números de página são removidos.
                </p>
              </section>
              <section className="panel tip-panel">
                <div className="flex gap-2 items-center text-[11px] text-primary">
                  <CircleHelp size={14} />
                  Antes de converter
                </div>
                <p>
                  Funciona melhor com PDFs de texto, como livros e artigos. PDFs
                  digitalizados (só imagens) viram um EPUB de imagens, sem
                  reconhecimento de texto. Tabelas, colunas e fórmulas podem
                  mudar. Até 1.000 páginas, sem senha.
                </p>
              </section>
            </>
          )}
        </aside>
      </div>
      <Footer />
    </main>
  );
}
function Footer() {
  return (
    <footer className="app-footer">
      <span className="footer-left">
        <Moon size={11} />
        Lua MediaPaper <span className="ml-2 opacity-60">v1.2.0</span>
      </span>
      <span>Feito com muito carinho para minha amiga Lua.</span>
    </footer>
  );
}
