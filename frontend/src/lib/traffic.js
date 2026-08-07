import http from "@/lib/api";

/**
 * Tell the server a page was looked at.
 *
 * Fire and forget, and deliberately silent: a counter must never delay a page or put an error
 * in front of a buyer. The server decides what counts - an administrator's own browsing and
 * anything that looks like a bot are dropped there, not here, so this cannot be gamed by
 * simply not calling it.
 */
export function ping(path, label = "") {
  http.post("/traffic/ping", { path, label }).catch(() => {});
}

export default ping;
