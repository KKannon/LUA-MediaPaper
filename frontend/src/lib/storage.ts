import { useState } from "react";
export function useStored<T>(key: string, fallback: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : fallback;
    } catch {
      return fallback;
    }
  });
  const update = (next: T | ((previous: T) => T)) =>
    setValue((previous) => {
      const result =
        typeof next === "function" ? (next as (p: T) => T)(previous) : next;
      try {
        localStorage.setItem(key, JSON.stringify(result));
      } catch {
        /* Keep working if storage is unavailable. */
      }
      return result;
    });
  return [value, update] as const;
}
export type Media = {
  id: string;
  name: string;
  description: string;
  url: string;
  type: "image" | "video" | "gif";
  thumbnail?: string;
  sourceUrl?: string;
};
export const presets: Media[] = [
  {
    id: "forest",
    name: "Entre a névoa",
    description: "Um respiro em meio ao verde.",
    url: "/wallpapers/forest.jpg",
    type: "image",
  },
  {
    id: "mountain",
    name: "Silêncio nas montanhas",
    description: "Onde o tempo desacelera.",
    url: "/wallpapers/mountain.jpg",
    type: "image",
  },
  {
    id: "sea",
    name: "Mar de calmaria",
    description: "Deixe os pensamentos flutuarem.",
    url: "/wallpapers/sea.jpg",
    type: "image",
  },
  {
    id: "dunes",
    name: "Luz do deserto",
    description: "O essencial também é bonito.",
    url: "/wallpapers/dunes.jpg",
    type: "image",
  },
];
export type Preferences = {
  clock: boolean;
  date: boolean;
  muted: boolean;
  autoplay: boolean;
  fit: "cover" | "contain";
  dim: number;
  hour24: boolean;
  keepAwake: boolean;
  /** Seconds without activity before /screen fades to the wallpaper; 0 never. */
  idle: number;
  weather: boolean;
  city: City | null;
};
export type City = { name: string; lat: number; lon: number };
export const defaultPreferences: Preferences = {
  clock: true,
  date: true,
  muted: true,
  autoplay: true,
  fit: "cover",
  dim: 0,
  hour24: true,
  keepAwake: true,
  idle: 15,
  weather: false,
  city: null,
};
export function csrf() {
  return (
    document.cookie
      .split("; ")
      .find((row) => row.startsWith("csrftoken="))
      ?.split("=")[1] || ""
  );
}
