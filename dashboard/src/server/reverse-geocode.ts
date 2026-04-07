/**
 * Géocodage inverse via Nominatim (OpenStreetMap).
 * Politique d’usage : https://operations.osmfoundation.org/policies/nominatim/
 * — User-Agent identifiable, pas plus d’≈1 req/s sans accord, cache côté serveur.
 */

type GpsLike = {
  lat: number;
  lon: number;
  mock?: boolean;
  fix?: boolean;
  satellites?: number;
} | null;

const cache = new Map<string, { address: string; at: number }>();
const TTL_MS = 60 * 60 * 1000;
const MIN_INTERVAL_MS = 1100;
let lastRequestAt = 0;

const UA =
  process.env.NOMINATIM_USER_AGENT?.trim() ||
  "MIRA-Dashboard/1.0 (console robot ; reverse-geocode for assistant)";

export function shouldReverseGeocodeGps(g: GpsLike): boolean {
  if (!g || g.mock) return false;
  if (g.fix === true) return true;
  if (g.satellites != null && g.satellites >= 1) return true;
  return false;
}

export async function reverseGeocodeCached(
  lat: number,
  lon: number,
): Promise<string | null> {
  if (process.env.NOMINATIM_DISABLE === "1") return null;
  const key = `${lat.toFixed(5)},${lon.toFixed(5)}`;
  const now = Date.now();
  const hit = cache.get(key);
  if (hit && now - hit.at < TTL_MS) return hit.address;

  const since = now - lastRequestAt;
  if (since < MIN_INTERVAL_MS) {
    await new Promise((r) => setTimeout(r, MIN_INTERVAL_MS - since));
  }
  lastRequestAt = Date.now();

  const url = new URL("https://nominatim.openstreetmap.org/reverse");
  url.searchParams.set("lat", String(lat));
  url.searchParams.set("lon", String(lon));
  url.searchParams.set("format", "json");
  url.searchParams.set("accept-language", "fr");

  try {
    const res = await fetch(url.toString(), {
      headers: { "User-Agent": UA },
    });
    if (!res.ok) return null;
    const data = (await res.json()) as {
      display_name?: string;
      error?: string;
    };
    if (data.error || !data.display_name) return null;
    cache.set(key, { address: data.display_name, at: Date.now() });
    return data.display_name;
  } catch {
    return null;
  }
}
