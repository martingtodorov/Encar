/**
 * What this visitor seems to like, learned from what they do and kept for 90 days.
 *
 * Three signals, weighted by how much intent each one shows: running a filtered search
 * (they told us), opening a car (they were curious), favouriting one (they mean it). Every
 * new signal decays the older ones a little, so the profile follows a buyer who changes
 * their mind instead of averaging their whole history forever.
 *
 * Everything stays on the visitor's machine: the profile is POSTed with the request that
 * needs it, so nothing about an anonymous browser is stored on our side.
 */
import { readCookie, readJsonCookie, writeCookie, writeJsonCookie } from "@/lib/cookies";

const VID = "ab_vid";
const TASTE = "ab_taste";
const DAYS = 90;

const KEEP = 6;        // values remembered per dimension
const DECAY = 0.9;     // how fast yesterday's interest fades
const FLOOR = 0.2;     // below this a value is forgotten

const WEIGHT = { search: 2, view: 1, favourite: 4 };

const EMPTY = { makes: {}, models: {}, fuels: {}, price: null, year: null, events: 0 };

export function visitorId() {
  let id = readCookie(VID);
  if (!id) {
    id = (crypto.randomUUID?.() || `v${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`);
    writeCookie(VID, id, DAYS);
  } else {
    writeCookie(VID, id, DAYS);   // sliding window: an active visitor is never forgotten
  }
  return id;
}

export function getTaste() {
  const raw = readJsonCookie(TASTE, null);
  if (!raw) return { ...EMPTY };
  return {
    makes: raw.makes || {},
    models: raw.models || {},
    fuels: raw.fuels || {},
    price: typeof raw.price === "number" ? raw.price : null,
    year: typeof raw.year === "number" ? raw.year : null,
    events: raw.events || 0,
  };
}

/** Enough signal to be worth showing a personalised row. */
export function hasTaste() {
  const p = getTaste();
  return p.events >= 2 && (Object.keys(p.makes).length > 0 || Object.keys(p.models).length > 0);
}

function decay(map) {
  const out = {};
  Object.entries(map).forEach(([k, v]) => {
    const next = Math.round(v * DECAY * 100) / 100;
    if (next >= FLOOR) out[k] = next;
  });
  return out;
}

function top(map) {
  return Object.fromEntries(
    Object.entries(map)
      .sort((a, b) => b[1] - a[1])
      .slice(0, KEEP)
  );
}

function blend(previous, value, weight) {
  if (!value) return previous;
  if (previous == null) return value;
  // A weighted step towards the newest number, so the profile tracks the current budget.
  const step = Math.min(0.5, 0.15 * weight);
  return Math.round(previous + (value - previous) * step);
}

function record(signals, weight, numbers = {}) {
  const p = getTaste();
  const next = {
    makes: decay(p.makes),
    models: decay(p.models),
    fuels: decay(p.fuels),
    price: blend(p.price, numbers.price, weight),
    year: blend(p.year, numbers.year, weight),
    events: Math.min(p.events + 1, 9999),
  };
  Object.entries(signals).forEach(([dim, values]) => {
    (values || []).filter(Boolean).forEach((value) => {
      const key = String(value).slice(0, 40);
      next[dim][key] = Math.round(((next[dim][key] || 0) + weight) * 100) / 100;
    });
  });
  next.makes = top(next.makes);
  next.models = top(next.models);
  next.fuels = top(next.fuels);
  writeJsonCookie(TASTE, next, DAYS);
  visitorId();
  return next;
}

/** A filtered search is the clearest statement of intent we ever get. */
export function noteSearch(payload) {
  if (!payload) return;
  const makes = payload.makes || (payload.make ? [payload.make] : []);
  const models = payload.models || (payload.model ? [payload.model] : []);
  const fuels = payload.fuels || [];
  if (!makes.length && !models.length && !fuels.length) return;   // browsing, not shopping
  const price = payload.price_max && payload.price_min
    ? Math.round((Number(payload.price_min) + Number(payload.price_max)) / 2)
    : Number(payload.price_max) || null;
  const year = Number(payload.year_min) || null;
  record({ makes, models, fuels }, WEIGHT.search, { price, year });
}

function fromCar(car) {
  return {
    signals: {
      makes: [car.manufacturer],
      models: [car.model],
      fuels: [car.fuel_type],
    },
    numbers: { price: car.sale_eur || null, year: car.form_year || null },
  };
}

export function noteView(car) {
  if (!car?.manufacturer) return;
  const { signals, numbers } = fromCar(car);
  record(signals, WEIGHT.view, numbers);
}

export function noteFavourite(car) {
  if (!car?.manufacturer) return;
  const { signals, numbers } = fromCar(car);
  record(signals, WEIGHT.favourite, numbers);
}
