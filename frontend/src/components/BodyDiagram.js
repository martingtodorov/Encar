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
  bg: { X: "Сменен", W: "Изправян или заваряван", C: "Корозия", A: "Драскотина",
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

// Our own top-down schematic: front at the top. Panels drawn as plain rounded blocks.
const SHAPES = {
  hood: { x: 112, y: 34, w: 96, h: 74 },
  roof: { x: 112, y: 150, w: 96, h: 128 },
  trunk_lid: { x: 112, y: 320, w: 96, h: 74 },
  front_fender_left: { x: 58, y: 74, w: 48, h: 70 },
  front_door_left: { x: 58, y: 150, w: 48, h: 78 },
  rear_door_left: { x: 58, y: 234, w: 48, h: 66 },
  quarter_panel_left: { x: 58, y: 306, w: 48, h: 74 },
  front_fender_right: { x: 214, y: 74, w: 48, h: 70 },
  front_door_right: { x: 214, y: 150, w: 48, h: 78 },
  rear_door_right: { x: 214, y: 234, w: 48, h: 66 },
  quarter_panel_right: { x: 214, y: 306, w: 48, h: 74 },
};

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
          viewBox="0 0 320 430"
          className="mx-auto h-[300px] w-auto shrink-0"
          role="img"
          aria-label={c.title}
        >
          <rect
            x="44" y="20" width="232" height="392" rx="60"
            className="fill-zinc-200 stroke-zinc-300 dark:fill-zinc-800 dark:stroke-zinc-700"
            strokeWidth="2"
          />
          {Object.entries(SHAPES).map(([slug, s]) => {
            const mark = marks[slug];
            const st = mark ? STATUS[mark.code] : null;
            return (
              <g key={slug} data-testid={`panel-${slug}`}>
                <rect
                  x={s.x} y={s.y} width={s.w} height={s.h} rx="7"
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
                    <circle
                      cx={s.x + s.w / 2} cy={s.y + s.h / 2} r="12"
                      fill={st.colour}
                    />
                    <text
                      x={s.x + s.w / 2} y={s.y + s.h / 2 + 5}
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
