import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { useScreenWakeLock } from "../src/lib/use-screen-wake-lock";

describe("live display wake lock", () => {
  const locks: Array<EventTarget & { release: ReturnType<typeof vi.fn> }> = [];
  const request = vi.fn(async () => {
    const lock = Object.assign(new EventTarget(), {
      release: vi.fn(async () => {
        lock.dispatchEvent(new Event("release"));
      }),
    });
    locks.push(lock);
    return lock;
  });
  beforeEach(() => {
    vi.useFakeTimers();
    locks.length = 0;
    request.mockClear();
    vi.stubGlobal("navigator", { wakeLock: { request } });
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  it("acquires a screen lock and releases it on navigation", async () => {
    const hook = renderHook(() => useScreenWakeLock(true));
    await act(async () => {});
    expect(request).toHaveBeenCalledWith("screen");
    hook.unmount();
    expect(locks[0].release).toHaveBeenCalledOnce();
  });
  it("recovers a released lock when the display becomes visible", async () => {
    renderHook(() => useScreenWakeLock(true));
    await act(async () => {});
    await act(async () => {
      await locks[0].release();
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(request).toHaveBeenCalledTimes(2);
  });
  it("does not request a lock for a hidden display", async () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    renderHook(() => useScreenWakeLock(true));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(request).not.toHaveBeenCalled();
  });
  it("releases the lock when the preference is disabled", async () => {
    const hook = renderHook(({ enabled }) => useScreenWakeLock(enabled), {
      initialProps: { enabled: true },
    });
    await act(async () => {});
    hook.rerender({ enabled: false });
    expect(locks[0].release).toHaveBeenCalledOnce();
  });
  it("works without the API and tolerates browser denial", async () => {
    request.mockRejectedValueOnce(new Error("Permission denied"));
    const hook = renderHook(() => useScreenWakeLock(true));
    await act(async () => {});
    expect(request).toHaveBeenCalledOnce();
    hook.unmount();
    vi.stubGlobal("navigator", {});
    expect(() => renderHook(() => useScreenWakeLock(true))).not.toThrow();
  });
});
