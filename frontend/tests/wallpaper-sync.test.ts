import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { useWallpaper } from "../src/lib/use-wallpaper";
import { defaultPreferences, presets } from "../src/lib/storage";
vi.mock("sonner", () => ({ toast: { error: vi.fn(), dismiss: vi.fn() } }));

describe("shared wallpaper synchronization", () => {
  let server = {
    media: presets[0],
    preferences: { ...defaultPreferences },
    revision: 3,
  };
  let failNextPatch = false;
  const patches: Array<Record<string, unknown>> = [];
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    patches.length = 0;
    failNextPatch = false;
    server = structuredClone({
      media: presets[0],
      preferences: defaultPreferences,
      revision: 3,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: unknown, options: RequestInit = {}) => {
        if (options.method === "PATCH") {
          if (failNextPatch) {
            failNextPatch = false;
            return new Response("{}", { status: 503 });
          }
          const body = JSON.parse(String(options.body));
          patches.push(body);
          server = {
            media: body.media || server.media,
            preferences: { ...server.preferences, ...body.preferences },
            revision: server.revision + 1,
          };
          return new Response(JSON.stringify(server));
        }
        if (
          (options.headers as Record<string, string>)?.["If-None-Match"] ===
          `"lua-wallpaper-${server.revision}"`
        )
          return new Response(null, { status: 304 });
        return new Response(JSON.stringify(server));
      }),
    );
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  it("propagates edits from one mounted page to an independent live reader", async () => {
    const editor = renderHook(() => useWallpaper(false)),
      live = renderHook(() => useWallpaper(true));
    await act(async () => {});
    await act(async () => {
      editor.result.current.setMedia(presets[2]);
      await vi.advanceTimersByTimeAsync(1200);
    });
    expect(live.result.current.media.id).toBe("sea");
    expect(patches).toHaveLength(1);
  });
  it("a live reader never uploads stale local preferences", async () => {
    server.revision = 0;
    localStorage.setItem("lua:media", JSON.stringify(presets[3]));
    const live = renderHook(() => useWallpaper(true));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(live.result.current.media.id).toBe("forest");
    expect(patches).toHaveLength(0);
  });
  it("coalesces quick changes and only sends the changed preference keys", async () => {
    const editor = renderHook(() => useWallpaper(false));
    await act(async () => {});
    await act(async () => {
      editor.result.current.setPreferences((p) => ({ ...p, dim: 20 }));
      editor.result.current.setPreferences((p) => ({ ...p, clock: false }));
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(patches).toHaveLength(1);
    expect(patches[0].preferences).toEqual({ dim: 20, clock: false });
  });
  it("keeps an optimistic edit during disconnection and retries it", async () => {
    const editor = renderHook(() => useWallpaper(false));
    await act(async () => {});
    failNextPatch = true;
    await act(async () => {
      editor.result.current.setMedia(presets[1]);
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(editor.result.current.media.id).toBe("mountain");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1800);
    });
    expect(server.media.id).toBe("mountain");
  });
  it("follows the server even when browser storage is blocked", async () => {
    server.revision = 0;
    server.media = presets[2];
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw Error("Storage blocked");
    });
    const hook = renderHook(() => useWallpaper(false));
    await act(async () => {});
    expect(hook.result.current.media.id).toBe("sea");
    expect(patches).toHaveLength(0);
  });
  it("can edit after changing from live to editor with an unchanged ETag", async () => {
    const hook = renderHook(({ readOnly }) => useWallpaper(readOnly), {
      initialProps: { readOnly: true },
    });
    await act(async () => {});
    hook.rerender({ readOnly: false });
    await act(async () => {});
    await act(async () => {
      hook.result.current.setMedia(presets[3]);
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(server.media.id).toBe("dunes");
  });
});
