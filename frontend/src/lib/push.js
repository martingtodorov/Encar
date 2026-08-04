import http from "@/lib/api";

/**
 * Web Push plumbing.
 *
 * The VAPID public key is fetched from the backend rather than baked into the bundle, so
 * rotating the pair does not need a rebuild. Everything here must be called from a real user
 * gesture — Safari in particular refuses a permission prompt that a page asks for on its own.
 */
const SW_PATH = "/sw.js";

export function pushSupported() {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/** iOS only allows push for a web app launched from the Home Screen, not a Safari tab. */
export function iosNeedsInstall() {
  if (typeof window === "undefined") return false;
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const standalone =
    window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone;
  return ios && !standalone;
}

function keyToBytes(base64) {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4))
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  const raw = window.atob(padded);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

export async function registerWorker() {
  if (!pushSupported()) return null;
  return navigator.serviceWorker.register(SW_PATH);
}

export async function currentSubscription() {
  if (!pushSupported()) return null;
  const registration = await navigator.serviceWorker.getRegistration(SW_PATH);
  return registration ? registration.pushManager.getSubscription() : null;
}

export async function enablePush() {
  if (!pushSupported()) throw new Error("unsupported");
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error(permission);

  await registerWorker();
  const registration = await navigator.serviceWorker.ready;
  let subscription = await registration.pushManager.getSubscription();
  if (!subscription) {
    const { data } = await http.get("/push/key");
    if (!data.key) throw new Error("push is not configured");
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyToBytes(data.key),
    });
  }
  await http.post("/push/subscribe", subscription.toJSON());
  return subscription;
}

export async function disablePush() {
  const subscription = await currentSubscription();
  if (!subscription) return;
  await http.post("/push/unsubscribe", { endpoint: subscription.endpoint, keys: {} });
  await subscription.unsubscribe();
}

export function sendTestPush() {
  return http.post("/push/test", {});
}
