/**
 * The dial-code list and the visitor's likely country.
 *
 * The list is static and the country comes from the server (a CDN header, or a cached IP
 * lookup), so the browser never talks to a geolocation provider itself and the visitor is
 * never asked for permission to guess a phone prefix.
 *
 * The IP guess is refreshed if the cached one is older than STALE_AFTER_MS — a tab left
 * open overnight, or opened over a VPN, still starts on the country the buyer is actually
 * in when they finally reach a phone field.
 */
import { useEffect, useState } from "react";
import http from "@/lib/api";

const STALE_AFTER_MS = 10 * 60 * 1000;      // 10 minutes

let pending = null;
let cached = null;
let cachedAt = 0;

/** Fetch /geo once per stale window. `refresh=true` forces a new request. */
export function loadDialCodes(refresh = false) {
  const stale = !cachedAt || Date.now() - cachedAt > STALE_AFTER_MS;
  if (cached && !refresh && !stale) return Promise.resolve(cached);
  if (pending) return pending;
  pending = http
    .get("/geo")
    .then(({ data }) => {
      // Only overwrite the country/dial fields — the code list itself is stable, so
      // keeping the last known list means a slow refetch never blanks the dropdown.
      const codes = data.codes && data.codes.length ? data.codes : (cached?.codes || []);
      cached = {
        codes,
        dial: data.dial || cached?.dial || "359",
        country: data.country || cached?.country || "",
      };
      cachedAt = Date.now();
      return cached;
    })
    .catch(() => {
      if (!cached) {
        // A failed guess must never cost the buyer a phone field: Bulgaria is the fallback.
        cached = { codes: [{ iso: "BG", name: "Bulgaria", dial: "359" }],
                   dial: "359", country: "" };
        cachedAt = Date.now();
      }
      return cached;
    })
    .finally(() => { pending = null; });
  return pending;
}

export function useDialCodes() {
  const [state, setState] = useState(cached);
  useEffect(() => {
    let alive = true;
    // The first mount serves the last known guess synchronously (if any), then always
    // asks the server for a fresh one so a stale country from earlier in the day (or a
    // VPN toggle) is corrected the moment a phone input appears.
    loadDialCodes().then((d) => alive && setState(d));
    return () => { alive = false; };
  }, []);
  return state || { codes: [], dial: "", country: "" };
}

/** Longest dial code that this E.164 number starts with. */
export function splitNumber(value, codes) {
  const digits = String(value || "").replace(/[^\d]/g, "");
  if (!digits) return { dial: "", national: "" };
  let best = "";
  codes.forEach(({ dial }) => {
    if (digits.startsWith(dial) && dial.length > best.length) best = dial;
  });
  return { dial: best, national: best ? digits.slice(best.length) : digits };
}
