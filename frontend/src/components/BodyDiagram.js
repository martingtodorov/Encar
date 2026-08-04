import { useApp } from "@/context/AppContext";

/**
 * Body condition diagram.
 *
 * Encar's inspection sheet reports each panel with a one-letter code — replaced, beaten or
 * welded, corroded, scratched, dented, damaged. Those codes are the single most useful
 * thing on the sheet and the single least readable, because upstream they arrive as Korean
 * text against panel numbers. Here they are drawn onto a plain top-down schematic of the
 * car so the shape of the damage is obvious at a glance: front-left fender replaced reads
 * very differently from a rear quarter panel welded.
 *
 * The drawing is our own simple schematic, and every word comes from the maps below rather
 * than from the Korean original.
 */

// Encar's status letters. Colours are chosen so "replaced" shouts and "scratch" whispers.
const STATUS = {
  X: { colour: "#dc2626", bg: "rgba(220,38,38,0.16)" },
  W: { colour: "#2563eb", bg: "rgba(37,99,235,0.16)" },
  C: { colour: "#d97706", bg: "rgba(217,119,6,0.16)" },
  A: { colour: "#64748b", bg: "rgba(100,116,139,0.16)" },
  U: { colour: "#4d7c0f", bg: "rgba(77,124,15,0.16)" },
  T: { colour: "#92400e", bg: "rgba(146,64,14,0.16)" },
};

const STATUS_LABELS = {
  bg: { X: "Сменен", W: "Изправян", C: "Корозия", A: "Драскотина",
        U: "Вдлъбнатина", T: "Повреда" },
  ro: { X: "Înlocuit", W: "Îndreptat sau sudat", C: "Coroziune", A: "Zgârietură",
        U: "Adâncitură", T: "Deteriorare" },
  en: { X: "Replaced", W: "Beaten or welded", C: "Corrosion", A: "Scratch",
        U: "Dent", T: "Damage" },
};

const PANEL_LABELS = {
  bg: {
    hood: "Преден капак", roof: "Таван", trunk_lid: "Заден капак",
    front_fender_left: "Преден калник (ляв)", front_fender_right: "Преден калник (десен)",
    front_door_left: "Предна врата (лява)", front_door_right: "Предна врата (дясна)",
    rear_door_left: "Задна врата (лява)", rear_door_right: "Задна врата (дясна)",
    quarter_panel_left: "Заден калник (ляв)", quarter_panel_right: "Заден калник (десен)",
    radiator_support: "Носач на радиатора", front_panel: "Предно табло",
    rear_panel: "Задно табло", cross_member: "Траверса",
    side_sill_left: "Прага (ляв)", side_sill_right: "Прага (десен)",
    inside_panel_left: "Вътрешен панел (ляв)", inside_panel_right: "Вътрешен панел (десен)",
    front_side_member_left: "Преден лонжерон (ляв)",
    front_side_member_right: "Преден лонжерон (десен)",
    rear_side_member_left: "Заден лонжерон (ляв)",
    rear_side_member_right: "Заден лонжерон (десен)",
    front_wheelhouse_left: "Предна калникова кутия (лява)",
    front_wheelhouse_right: "Предна калникова кутия (дясна)",
    rear_wheelhouse_left: "Задна калникова кутия (лява)",
    rear_wheelhouse_right: "Задна калникова кутия (дясна)",
    pillar_front_left: "Колона A (лява)", pillar_front_right: "Колона A (дясна)",
    pillar_centre_left: "Колона B (лява)", pillar_centre_right: "Колона B (дясна)",
    pillar_rear_left: "Колона C (лява)", pillar_rear_right: "Колона C (дясна)",
    trunk_floor: "Под на багажника",
  },
  ro: {
    hood: "Capotă", roof: "Plafon", trunk_lid: "Capac portbagaj",
    front_fender_left: "Aripă față (stânga)", front_fender_right: "Aripă față (dreapta)",
    front_door_left: "Ușă față (stânga)", front_door_right: "Ușă față (dreapta)",
    rear_door_left: "Ușă spate (stânga)", rear_door_right: "Ușă spate (dreapta)",
    quarter_panel_left: "Aripă spate (stânga)", quarter_panel_right: "Aripă spate (dreapta)",
    radiator_support: "Suport radiator", front_panel: "Panou față",
    rear_panel: "Panou spate", cross_member: "Traversă",
    side_sill_left: "Prag (stânga)", side_sill_right: "Prag (dreapta)",
    inside_panel_left: "Panou interior (stânga)", inside_panel_right: "Panou interior (dreapta)",
    front_side_member_left: "Longeron față (stânga)",
    front_side_member_right: "Longeron față (dreapta)",
    rear_side_member_left: "Longeron spate (stânga)",
    rear_side_member_right: "Longeron spate (dreapta)",
    front_wheelhouse_left: "Carcasă roată față (stânga)",
    front_wheelhouse_right: "Carcasă roată față (dreapta)",
    rear_wheelhouse_left: "Carcasă roată spate (stânga)",
    rear_wheelhouse_right: "Carcasă roată spate (dreapta)",
    pillar_front_left: "Stâlp A (stânga)", pillar_front_right: "Stâlp A (dreapta)",
    pillar_centre_left: "Stâlp B (stânga)", pillar_centre_right: "Stâlp B (dreapta)",
    pillar_rear_left: "Stâlp C (stânga)", pillar_rear_right: "Stâlp C (dreapta)",
    trunk_floor: "Podea portbagaj",
  },
  en: {
    hood: "Bonnet", roof: "Roof", trunk_lid: "Boot lid",
    front_fender_left: "Front wing (left)", front_fender_right: "Front wing (right)",
    front_door_left: "Front door (left)", front_door_right: "Front door (right)",
    rear_door_left: "Rear door (left)", rear_door_right: "Rear door (right)",
    quarter_panel_left: "Rear quarter (left)", quarter_panel_right: "Rear quarter (right)",
    radiator_support: "Radiator support", front_panel: "Front panel",
    rear_panel: "Rear panel", cross_member: "Cross member",
    side_sill_left: "Sill (left)", side_sill_right: "Sill (right)",
    inside_panel_left: "Inner panel (left)", inside_panel_right: "Inner panel (right)",
    front_side_member_left: "Front side member (left)",
    front_side_member_right: "Front side member (right)",
    rear_side_member_left: "Rear side member (left)",
    rear_side_member_right: "Rear side member (right)",
    front_wheelhouse_left: "Front wheelhouse (left)",
    front_wheelhouse_right: "Front wheelhouse (right)",
    rear_wheelhouse_left: "Rear wheelhouse (left)",
    rear_wheelhouse_right: "Rear wheelhouse (right)",
    pillar_front_left: "A-pillar (left)", pillar_front_right: "A-pillar (right)",
    pillar_centre_left: "B-pillar (left)", pillar_centre_right: "B-pillar (right)",
    pillar_rear_left: "C-pillar (left)", pillar_rear_right: "C-pillar (right)",
    trunk_floor: "Boot floor",
  },
};

const COPY = {
  bg: { title: "Състояние на купето", clean: "Няма отбелязани щети по панелите",
        structural: "Отбелязано и по конструкцията",
        note: "По данни от инспекционния лист на Encar." },
  ro: { title: "Starea caroseriei", clean: "Nicio deteriorare marcată pe panouri",
        structural: "Marcat și pe structură",
        note: "Conform fișei de inspecție Encar." },
  en: { title: "Body condition", clean: "No panel findings recorded",
        structural: "Also marked on the structure",
        note: "From Encar's inspection sheet." },
};

// Our own top-down schematic, drawn as a low, wide-hipped coupe rather than a rectangle:
// a tapered nose, a cabin pinched in behind the windscreen and haunches over the rear
// wheels, so the shape reads as a car at a glance. Panels are curved bands that follow the
// body, and `cx`/`cy` is where the status badge sits on each one.
const SHAPES = {
  hood: {
    d: "M160,36 C141,36 129,46 123,66 C117,86 115,98 115,112 L205,112 C205,98 203,86 197,66 C191,46 179,36 160,36 Z",
    cx: 160, cy: 80,
  },
  roof: {
    d: "M121,130 C116,158 116,200 120,240 L200,240 C204,200 204,158 199,130 Z",
    cx: 160, cy: 188,
  },
  trunk_lid: {
    d: "M120,300 C114,332 112,372 116,404 C128,414 142,418 160,418 C178,418 192,414 204,404 C208,372 206,332 200,300 Z",
    cx: 160, cy: 360,
  },
  front_fender_left: {
    d: "M112,58 Q97,96 92,146 L118,146 Q123,96 138,58 Z",
    cx: 108, cy: 104,
  },
  front_door_left: {
    d: "M92,150 Q95,190 96,228 L122,228 Q121,190 118,150 Z",
    cx: 107, cy: 190,
  },
  rear_door_left: {
    d: "M96,232 Q92,265 90,298 L116,298 Q118,265 122,232 Z",
    cx: 105, cy: 265,
  },
  quarter_panel_left: {
    d: "M90,302 Q84,362 104,416 L126,404 Q110,360 116,302 Z",
    cx: 106, cy: 356,
  },
  front_fender_right: {
    d: "M208,58 Q223,96 228,146 L202,146 Q197,96 182,58 Z",
    cx: 212, cy: 104,
  },
  front_door_right: {
    d: "M228,150 Q225,190 224,228 L198,228 Q199,190 202,150 Z",
    cx: 213, cy: 190,
  },
  rear_door_right: {
    d: "M224,232 Q228,265 230,298 L204,298 Q202,265 198,232 Z",
    cx: 215, cy: 265,
  },
  quarter_panel_right: {
    d: "M230,302 Q236,362 216,416 L194,404 Q210,360 204,302 Z",
    cx: 214, cy: 356,
  },
};

// The body itself, plus the parts that are not panels but make it read as a car: wheels,
// windscreen, rear glass and mirrors. Narrow nose, pinched waist, haunches over the rear
// wheels that are WIDER than the front — that proportion is what makes a top view read as
// a sports coupe instead of a saloon.
const BODY =
  "M160,22 C134,22 118,34 112,58 C102,86 92,104 92,130 C92,160 95,182 96,210 " +
  "C97,244 90,286 84,320 C80,360 88,400 104,420 C116,436 136,441 160,441 " +
  "C184,441 204,436 216,420 C232,400 240,360 236,320 C230,286 223,244 224,210 " +
  "C225,182 228,160 228,130 C228,104 218,86 208,58 C202,34 186,22 160,22 Z";

export const BodyDiagram = ({ panels }) => {
  const { lang } = useApp();
  if (!panels?.available) return null;

  const L = PANEL_LABELS[lang] || PANEL_LABELS.en;
  const S = STATUS_LABELS[lang] || STATUS_LABELS.en;
  const c = COPY[lang] || COPY.en;

  // First status wins the colour: a panel that was replaced AND welded is, to a buyer,
  // simply a replaced panel.
  const marks = {};
  const structural = [];
  (panels.findings || []).forEach((f) => {
    const code = (f.statuses || [])[0];
    if (!code || !STATUS[code]) return;
    if (f.slug && SHAPES[f.slug]) marks[f.slug] = { code, statuses: f.statuses };
    else if (f.slug) structural.push({ slug: f.slug, code });
  });

  const used = [...new Set(Object.values(marks).map((m) => m.code)
    .concat(structural.map((s) => s.code)))];

  return (
    <section
      data-testid="body-diagram"
      className="rounded-[16px] border border-border bg-card p-5 shadow-sm"
    >
      <h2 className="text-[14.5px] font-semibold text-foreground">{c.title}</h2>

      <div className="mt-3 flex flex-col gap-5 sm:flex-row sm:items-start">
        <svg
          viewBox="0 0 320 460"
          className="mx-auto h-[320px] w-auto shrink-0"
          role="img"
          aria-label={c.title}
        >
          {/* wheels first, so the body sits over them the way a top view really looks */}
          {[
            [78, 110], [224, 110], [68, 298], [234, 298],
          ].map(([x, y]) => (
            <rect
              key={`${x}-${y}`}
              x={x} y={y} width="18" height="54" rx="8"
              className="fill-zinc-400 dark:fill-zinc-700"
            />
          ))}

          <path
            d={BODY}
            className="fill-zinc-200 stroke-zinc-300 dark:fill-zinc-800 dark:stroke-zinc-700"
            strokeWidth="2"
          />

          {/* glass and mirrors: not panels, just enough to read as a car */}
          <path
            d="M119,113 L201,113 L199,128 L121,128 Z"
            className="fill-zinc-300/80 dark:fill-zinc-700/80"
          />
          <path
            d="M121,246 C117,266 117,283 119,296 L201,296 C203,283 203,266 199,246 Z"
            className="fill-zinc-300/80 dark:fill-zinc-700/80"
          />
          {[84, 236].map((x) => (
            <ellipse
              key={x}
              cx={x} cy="141" rx="8" ry="4.5"
              className="fill-zinc-300 dark:fill-zinc-700"
            />
          ))}

          {Object.entries(SHAPES).map(([slug, s]) => {
            const mark = marks[slug];
            const st = mark ? STATUS[mark.code] : null;
            return (
              <g key={slug} data-testid={`panel-${slug}`}>
                <path
                  d={s.d}
                  fill={st ? st.bg : undefined}
                  stroke={st ? st.colour : undefined}
                  strokeWidth={st ? 2 : 1.5}
                  className={
                    st
                      ? ""
                      : "fill-white stroke-zinc-300 dark:fill-zinc-900 dark:stroke-zinc-700"
                  }
                />
                {mark && (
                  <>
                    <circle cx={s.cx} cy={s.cy} r="12" fill={st.colour} />
                    <text
                      x={s.cx} y={s.cy + 5}
                      textAnchor="middle" fontSize="14" fontWeight="700" fill="#fff"
                    >
                      {mark.code}
                    </text>
                  </>
                )}
              </g>
            );
          })}
        </svg>

        <div className="min-w-0 flex-1">
          {used.length === 0 ? (
            <p data-testid="body-diagram-clean" className="text-[13px] text-muted-foreground">
              {c.clean}
            </p>
          ) : (
            <ul data-testid="body-diagram-legend" className="flex flex-col gap-2">
              {used.map((code) => (
                <li key={code} className="flex items-center gap-2.5">
                  <span
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[12px] font-bold text-white"
                    style={{ backgroundColor: STATUS[code].colour }}
                  >
                    {code}
                  </span>
                  <span className="text-[13px] text-foreground">{S[code]}</span>
                </li>
              ))}
            </ul>
          )}

          {Object.keys(marks).length > 0 && (
            <ul className="mt-4 flex flex-col gap-1.5">
              {Object.entries(marks).map(([slug, m]) => (
                <li
                  key={slug}
                  data-testid={`body-finding-${slug}`}
                  className="flex items-baseline justify-between gap-3 border-b border-border/60 pb-1.5 text-[12.5px]"
                >
                  <span className="text-muted-foreground">{L[slug] || slug}</span>
                  <span className="font-medium" style={{ color: STATUS[m.code].colour }}>
                    {m.statuses.map((s) => S[s] || s).join(" · ")}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {structural.length > 0 && (
            <div className="mt-4">
              <p className="text-[12px] font-medium text-foreground">{c.structural}</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {structural.map((s) => (
                  <span
                    key={s.slug}
                    data-testid={`body-structural-${s.slug}`}
                    className="rounded-full border px-2 py-0.5 text-[11.5px]"
                    style={{ borderColor: STATUS[s.code].colour, color: STATUS[s.code].colour }}
                  >
                    {L[s.slug] || s.slug} · {S[s.code]}
                  </span>
                ))}
              </div>
            </div>
          )}

          <p className="mt-4 text-[11.5px] text-muted-foreground">{c.note}</p>
        </div>
      </div>
    </section>
  );
};

export default BodyDiagram;
