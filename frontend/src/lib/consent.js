/**
 * Consent for everything that is NOT strictly necessary.
 *
 * ePrivacy rule we are implementing: nothing outside the strictly necessary category may be
 * written to - or read from - the visitor's device before they have actively agreed to that
 * category. So this module is the ONLY gate: `allows(category)` is checked at every write,
 * and until a decision exists it answers false for everything.
 *
 * The decision itself is stored as a record, not a flag, because we have to be able to show
 * WHAT was agreed and WHEN: `{ v: policy version, ts: ISO timestamp, cats: {...} }`. Bumping
 * POLICY_VERSION invalidates every stored decision, so a change to the policy asks again
 * instead of relying on consent given for a different document.
 *
 * The record cookie itself is strictly necessary (it stores a refusal just as much as an
 * agreement), which is why it may be written before any consent.
 */
import { dropCookie, readCookie, writeJsonCookie } from "@/lib/cookies";

/** Bump this whenever the cookie or privacy policy changes materially. */
export const POLICY_VERSION = "2026-06-08";

/** Everything we could ever set beyond the strictly necessary. No marketing category:
 *  we run no advertising networks and embed no third-party pixels. */
export const CATEGORIES = ["personalisation", "statistics"];

const COOKIE = "ab_consent";
const DAYS = 365;

/**
 * A SECOND copy of the decision, alive for 90 days, kept for one purpose: a visitor who
 * decides while signed out and creates an account later should not be asked again — the
 * choice they already made travels up to the account on their first sign-in. After 90 days
 * the cookie is gone and nothing is carried, which is the retention the owner asked for.
 */
const CARRY = "ab_consent_carry";
export const CARRY_DAYS = 90;

/**
 * The operator can ask EVERYBODY to decide again (Admin → Consent). It is one timestamp
 * rather than a flag per person, because a guest has no row of ours to flag. A decision
 * taken before it counts as no decision at all: the dialog opens, and `allows()` says no
 * meanwhile, so nothing optional is written while the answer is outstanding.
 */
let reaskAt = "";

// Written only under `personalisation`; cleared the moment it is refused or withdrawn.
const PERSONALISATION_COOKIES = ["ab_taste", "ab_vid", "ab_track"];

const listeners = new Set();

/** Re-render whatever depends on the decision (the banner, the analytics loader). */
export function onConsentChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function announce() {
  listeners.forEach((fn) => {
    try {
      fn(record());
    } catch (e) {
      /* a broken listener must not break the next one */
    }
  });
}

export function record() {
  const raw = readCookie(COOKIE);
  if (!raw) return null;
  // Installs from before categories existed stored the bare strings "all" / "necessary".
  if (raw === "all") {
    return { v: "legacy", ts: "", cats: { personalisation: true, statistics: true } };
  }
  if (raw === "necessary") return { v: "legacy", ts: "", cats: {} };
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    return { v: parsed.v || "", ts: parsed.ts || "", cats: parsed.cats || {} };
  } catch (e) {
    return null;
  }
}

/** True only for a decision taken against the CURRENT policy, and not superseded by a
 *  request from the operator to decide again. */
export function hasDecision() {
  const r = record();
  return !!r && r.v === POLICY_VERSION && !superseded(r);
}

/** Was this decision taken before the operator asked everybody again? */
function superseded(r) {
  if (!reaskAt) return false;
  return !r.ts || r.ts < reaskAt;
}

/** Told by the server (`GET /api/consent/policy`) on the first page view. */
export function setReaskStamp(iso) {
  const next = iso || "";
  if (next === reaskAt) return;
  reaskAt = next;
  announce();
}

export function reaskStamp() {
  return reaskAt;
}

export function allows(category) {
  const r = record();
  if (!r || r.v !== POLICY_VERSION || superseded(r)) return false;
  return !!r.cats[category];
}

/** The categories the visitor has agreed to, for seeding the settings toggles. */
export function chosen() {
  const r = record();
  const cats = r && r.v === POLICY_VERSION ? r.cats : {};
  return Object.fromEntries(CATEGORIES.map((c) => [c, !!cats[c]]));
}

export function save(cats) {
  const clean = Object.fromEntries(CATEGORIES.map((c) => [c, !!cats?.[c]]));
  const rec = { v: POLICY_VERSION, ts: new Date().toISOString(), cats: clean };
  writeJsonCookie(COOKIE, rec, DAYS);
  // The 90-day carry copy: if this visitor creates an account within that window, this is
  // the decision that goes onto it, exactly as it was made here.
  writeJsonCookie(CARRY, rec, CARRY_DAYS);
  // Refusing or withdrawing has to actually remove what was stored under that category,
  // otherwise the refusal is cosmetic.
  if (!clean.personalisation) PERSONALISATION_COOKIES.forEach(dropCookie);
  announce();
  return clean;
}

/** The decision waiting to be attached to an account, or null. */
export function carried() {
  const raw = readCookie(CARRY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || !parsed.cats) return null;
    return { v: parsed.v || "", ts: parsed.ts || "", cats: parsed.cats };
  } catch (e) {
    return null;
  }
}

/** Once it is on the account there is no reason to keep carrying it. */
export const dropCarried = () => dropCookie(CARRY);

export const acceptAll = () =>
  save(Object.fromEntries(CATEGORIES.map((c) => [c, true])));

export const rejectAll = () => save({});

/**
 * Take on a decision made ON ANOTHER DEVICE, exactly as it was made.
 *
 * `save()` stamps the CURRENT policy version, which would silently turn a decision taken
 * against an older policy into agreement to the new one — the visitor would never be asked
 * again after a policy change. This keeps the original version and timestamp, so
 * `hasDecision()` still says no when the policy has moved on.
 */
export function adopt(rec) {
  if (!rec || typeof rec !== "object" || !rec.cats) return null;
  const clean = Object.fromEntries(CATEGORIES.map((c) => [c, !!rec.cats[c]]));
  writeJsonCookie(COOKIE, { v: rec.v || "", ts: rec.ts || "", cats: clean }, DAYS);
  if (!clean.personalisation) PERSONALISATION_COOKIES.forEach(dropCookie);
  announce();
  return clean;
}

/** A short, human summary for the account page and for the operator's record. */
export function summary() {
  const r = record();
  if (!r) return "";
  const on = CATEGORIES.filter((c) => r.cats[c]);
  if (!on.length) return "necessary";
  return on.length === CATEGORIES.length ? "all" : on.join("+");
}
