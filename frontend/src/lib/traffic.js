import http from "@/lib/api";

/**
 * Short, readable names for the admin bar.
 *
 * The first attempt read the document title, which works for a car ("Hyundai Santa Fe DM") but
 * put a whole SEO headline on the home page — "Автомобили от Корея с крайна цена до България |
 * Encar" — and one of those swamps the strip. Known routes get a fixed short name; only a car
 * page needs its title, because only a car page has a name we cannot know in advance.
 */
const NAMES = {
  "": "Начало",
  saved: "Любими",
  searches: "Запазени търсения",
  "how-it-works": "Как работи",
  track: "Проследяване",
  login: "Вход",
  "verify-email": "Потвърждаване на имейл",
  "forgot-password": "Забравена парола",
  "reset-password": "Нова парола",
  account: "Профил",
  admin: "Админ",
  terms: "Условия",
  privacy: "Поверителност",
  cookies: "Бисквитки",
  contact: "Контакт",
  faq: "Въпроси",
  fees: "Такси",
  purchases: "Моите покупки",
  "payment/success": "Плащане: успех",
  "payment/cancel": "Плащане: отказ",
};

const CAR_MAX = 42;

export function labelFor(path, title = "") {
  const key = (path || "/").replace(/^\/+|\/+$/g, "");
  if (key in NAMES) return NAMES[key];
  if (key.startsWith("car/")) {
    // Car titles are set as "{name} · Encar"; take the name and keep it short enough that
    // several cars still fit on one line.
    const name = title.split(/\s+[·|]\s+/)[0].trim();
    return name ? name.slice(0, CAR_MAX) : "Автомобил";
  }
  return `/${key}`.slice(0, CAR_MAX);
}

/**
 * Tell the server a page was looked at.
 *
 * Fire and forget, and deliberately silent: a counter must never delay a page or put an error in
 * front of a buyer. The server decides what counts — an administrator's own browsing and anything
 * that looks like a bot are dropped there, not here, so this cannot be gamed by not calling it.
 */
export function ping(path, label = "") {
  http.post("/traffic/ping", { path, label }).catch(() => {});
}

export default ping;
