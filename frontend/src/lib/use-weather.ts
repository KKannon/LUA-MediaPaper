import { useEffect, useState } from "react";

export type Weather = {
  city: string;
  temperature: number;
  description: string;
  day: boolean;
};

/** Current temperature for the city chosen in Definições; refreshed every 10 minutes. */
export function useWeather(enabled: boolean, cityKey: string) {
  const [weather, setWeather] = useState<Weather | null>(null);
  useEffect(() => {
    if (!enabled) {
      setWeather(null);
      return;
    }
    let active = true;
    const load = () =>
      fetch("/api/weather", { cache: "no-store" })
        .then((r) => r.json())
        .then((data) => {
          if (active)
            setWeather(
              data.enabled && typeof data.temperature === "number"
                ? data
                : null,
            );
        })
        .catch(() => {});
    void load();
    const timer = setInterval(load, 10 * 60 * 1000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [enabled, cityKey]);
  return weather;
}
