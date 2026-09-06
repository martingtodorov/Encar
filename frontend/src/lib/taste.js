/**
 * What this buyer seems to want, learned from what they do.
 *
 * Signals, weighted by how much intent each one shows:
 *   running a filtered search (they told us)          weight 2
 *   opening a car                                     weight 1
 *   still reading it 30 seconds later                 weight 2 more
 *   favouriting it                                    weight 4
 * Every new signal decays the older ones a little, so the profile follows a buyer who
 * changes their mind instead of averaging their whole history for ever.
 *
 * Price and mileage are kept as SAMPLES, not averages: the last twelve cars they lingered
 * on, each with its weight. The backend turns those into the range they are really shopping
 * in, which a single mean would hide.
 *
 * Signed out, all of this lives in a 90-day cookie on their own machine and is POSTed with
 * the request that needs it. Signed in, the same profile is mirrored onto the account so it
 * follows them between devices — and so the operator can see what a buyer is after.
 */
import http, { putCarriedConsent } from "@/lib/api";
import {
  allows,
  adopt as adoptConsent,
  carried as carriedConsent,
  dropCarried,
  record as consentRecord,
  save as saveConsent,
  summary,
} from "@/lib/consent";
import { readCookie, readJsonCookie, writeCookie, writeJsonCookie } from "@/lib/cookies";

const VID = "ab_vid";
const TASTE = "ab_taste";
const SIGNED = "ab_signed";      // set by AuthContext; a cookie would be httpOnly and unreadable

const DAYS = 90;
const KEEP = 6;                  // values remembered per dimension
const SAMPLES = 12;              // price/mileage observations kept
const DECAY = 0.9;
const FLOOR = 0.2;

export const WEIGHT = { search: 2, view: 1, dwell: 2, favourite: 4 };

const EMPTY = { makes: {}, models: {}, fuels: {}, samples: [], events: 0 };

export function getConsent() {
  return summary();
}

/** Adopt a decision recorded on the account, so a new device is not asked again. Accepts the
 *  legacy "all"/"necessary" strings as well as the category record. */
export function setConsent(value) {
  if (consentRecord()) return;                 // this device has already decided
  if (value && typeof value === "object" && value.cats) {
    // Adopted AS IT WAS MADE, version and timestamp included: re-stamping it with today's
    // policy version would mean a policy change never asks the buyer again.
    adoptConsent(value);
    return;
  }
  saveConsent(value === "all" ? { personalisation: true, statistics: true } : {});
}

export function visitorId() {
  let id = readCookie(VID);
  if (!id) {
    id = crypto.randomUUID?.()
      || `v${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
  }
  writeCookie(VID, id, DAYS);   // sliding window: an active visitor is never forgotten
  return id;
}

export function getTaste() {
  const raw = readJsonCookie(TASTE, null);
  if (!raw) return { ...EMPTY, samples: [] };
  return {
    makes: raw.makes || {},
    models: raw.models || {},
    fuels: raw.fuels || {},
    samples: Array.isArray(raw.samples) ? raw.samples.slice(0, SAMPLES) : [],
    events: raw.events || 0,
  };
}

/** Enough signal to be worth personalising anything. */
export function hasTaste() {
  const p = getTaste();
  return p.events >= 2
    && (Object.keys(p.makes).length > 0 || Object.keys(p.models).length > 0);
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
  return Object.fromEntries(Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, KEEP));
}

let syncTimer = null;

/** Mirror the profile onto the account, so it follows the buyer and the operator can see it. */
function sync(profile) {
  if (localStorage.getItem(SIGNED) !== "1") return;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => {
    http.post("/auth/taste", { ...profile, consent: getConsent() }).catch(() => {});
  }, 1500);
}

function record(signals, weight, sample = null) {
  // No consent, no profiling. This is the single gate: every signal comes through here.
  if (!allows("personalisation")) return null;

  const p = getTaste();
  const next = {
    makes: decay(p.makes),
    models: decay(p.models),
    fuels: decay(p.fuels),
    samples: p.samples,
    events: Math.min(p.events + 1, 9999),
  };

  Object.entries(signals).forEach(([dim, values]) => {
    (values || []).filter(Boolean).forEach((value) => {
      const key = String(value).slice(0, 40);
      next[dim][key] = Math.round(((next[dim][key] || 0) + weight) * 100) / 100;
    });
  });

  if (sample && (sample.price || sample.mileage)) {
    next.samples = [
      [Math.round(sample.price || 0), Math.round(sample.mileage || 0), weight],
      ...p.samples,
    ].slice(0, SAMPLES);
  }

  next.makes = top(next.makes);
  next.models = top(next.models);
  next.fuels = top(next.fuels);

  writeJsonCookie(TASTE, next, DAYS);
  visitorId();
  sync(next);
  return next;
}

/** A filtered search is the clearest statement of intent we ever get. */
export function noteSearch(payload) {
  if (!payload) return;
  const makes = payload.makes || (payload.make ? [payload.make] : []);
  const models = payload.models || (payload.model ? [payload.model] : []);
  const fuels = payload.fuels || [];
  if (!makes.length && !models.length && !fuels.length) return;   // browsing, not shopping
  const price = payload.price_min && payload.price_max
    ? (Number(payload.price_min) + Number(payload.price_max)) / 2
    : Number(payload.price_max) || 0;
  const mileage = payload.mileage_min && payload.mileage_max
    ? (Number(payload.mileage_min) + Number(payload.mileage_max)) / 2
    : Number(payload.mileage_max) || 0;
  record({ makes, models, fuels }, WEIGHT.search,
         price || mileage ? { price, mileage } : null);
}

// The car page and the grid do not speak the same shape: a row carries `sale_eur` and
// `mileage` at the top level, while the DETAIL payload keeps the price in `quote.suggested_sale`
// and the mileage in `spec.mileage`. Reading only the row's field is how every price and
// mileage sample landed as 0 - the profile then had no range at all, so the shelf ranked cars
// on nothing but the make and answered a €90,000 M2 with a €9,000 E60.
function priceOf(car) {
  return Number(car.sale_eur ?? car.quote?.suggested_sale ?? 0) || 0;
}

function mileageOf(car) {
  return Number(car.mileage ?? car.spec?.mileage ?? 0) || 0;
}

function fromCar(car) {
  return {
    signals: { makes: [car.manufacturer], models: [car.model], fuels: [car.fuel_type] },
    sample: { price: priceOf(car), mileage: mileageOf(car) },
  };
}

/** `weight` lets the caller say how long the buyer stayed on the car. */
export function noteView(car, weight = WEIGHT.view) {
  if (!car?.manufacturer) return;
  const { signals, sample } = fromCar(car);
  record(signals, weight, sample);
}

export function noteFavourite(car) {
  if (!car?.manufacturer) return;
  const { signals, sample } = fromCar(car);
  record(signals, WEIGHT.favourite, sample);
}

export function markSignedIn(on) {
  if (on) localStorage.setItem(SIGNED, "1");
  else localStorage.removeItem(SIGNED);
}

/** Push the consent decision to the account, so a signed-in buyer is asked once, not per device. */
export function syncConsent() {
  if (localStorage.getItem(SIGNED) !== "1") return;
  // The record, not just the summary: we have to be able to show what was agreed and when.
  http.post("/auth/taste", {
    ...getTaste(),
    consent: getConsent(),
    consent_record: consentRecord() || {},
  }).catch(() => {});
  dropCarried();       // it is on the account now; nothing left to carry
}

/**
 * Carry a decision made while signed OUT onto the account that has just appeared.
 *
 * Without this, a visitor who chose in the dialog and signed up ten minutes later arrived as
 * an account with no consent on record — which is why almost none of them had one. The
 * carry copy lives 90 days (see `CARRY_DAYS`), and an older decision never overwrites a
 * newer one already on the account; the server enforces that too.
 */
export async function carryConsent(user) {
  const rec = carriedConsent();
  if (!rec) return false;
  const accountTs = user?.consent_record?.ts || "";
  if (accountTs && accountTs >= (rec.ts || "")) {
    dropCarried();
    return false;
  }
  try {
    await putCarriedConsent(rec);
    dropCarried();
    return true;
  } catch (e) {
    return false;            // next sign-in tries again; the cookie is still there
  }
}
