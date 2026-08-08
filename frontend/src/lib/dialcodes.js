/**
 * The dial-code list and the visitor's likely country, fetched ONCE per page load.
 *
 * The list is static and the country comes from the server (a CDN header, or a cached IP
 * lookup), so the browser never talks to a geolocation provider itself and the visitor is
 * never asked for permission to guess a phone prefix.
 */
import { useEffect, useState } from "react";
import http from "@/lib/api";

let pending = null;
let cached = null;

export function loadDialCodes() {
  if (cached) return Promise.resolve(cached);
  if (!pending) {
    pending = http
      .get("/geo")
      .then(({ data }) => {
        cached = {
          codes: data.codes || [],
          dial: data.dial || "359",
          country: data.country || "",
        };
        return cached;
      })
      .catch(() => {
        // A failed guess must never cost the buyer a phone field: Bulgaria is the fallback.
        cached = { codes: [{ iso: "BG", name: "Bulgaria", dial: "359" }], dial: "359", country: "" };
        return cached;
      });
  }
  return pending;
}

export function useDialCodes() {
  const [state, setState] = useState(cached);
  useEffect(() => {
    let alive = true;
    loadDialCodes().then((d) => alive && setState(d));
    return () => {
      alive = false;
    };
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
