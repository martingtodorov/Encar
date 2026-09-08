/**
 * How many steps back inside the app we actually own.
 *
 * "Back to results" used to decide by `location.key !== "default"`, on the assumption that
 * anything other than the first entry meant the visitor had navigated here from the list.
 * That assumption is wrong the moment a language redirect is involved: `/bg/car/...` opened
 * cold is replaced with `/en/car/...`, and a REPLACE gets a fresh key too — so a shared link
 * looked like in-app history and Back stepped out of the site (or bounced through the
 * redirect) instead of landing on the car's own make/model search.
 *
 * So the pushes are counted instead: only a real PUSH we made adds a step, only a POP spends
 * one, and a redirect (REPLACE) changes nothing.
 */
let depth = 0;

export function noteNav(type) {
  if (type === "PUSH") depth += 1;
  else if (type === "POP") depth = Math.max(0, depth - 1);
}

/** Is there an entry of OURS to go back to? */
export function canPop() {
  return depth > 0;
}
