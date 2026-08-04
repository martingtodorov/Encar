import { AlertTriangle, CheckCircle2, Wrench, XCircle } from "lucide-react";
import { useApp } from "@/context/AppContext";

/**
 * Mechanical checks from the inspection sheet, beside the body diagram.
 *
 * The sheet tests a few dozen items and nearly all of them come back fine, so a full list
 * would bury the one or two that matter. Each section shows a verdict and only the items
 * that are not fine get named — a "slight seepage from the cylinder block" is exactly the
 * sort of thing a buyer wants surfaced, and the other forty passes are noise.
 */

const SECTION_LABELS = {
  bg: {
    engine: "Двигател", transmission: "Скоростна кутия", drivetrain: "Задвижване",
    steering: "Кормилно управление", braking: "Спирачки", electrics: "Електрика",
    fuel: "Горивна система", high_voltage: "Високоволтова система",
    self_diagnosis: "Електронна диагностика",
  },
  ro: {
    engine: "Motor", transmission: "Cutie de viteze", drivetrain: "Transmisie",
    steering: "Direcție", braking: "Frâne", electrics: "Instalație electrică",
    fuel: "Sistem de alimentare", high_voltage: "Sistem de înaltă tensiune",
    self_diagnosis: "Diagnoză electronică",
  },
  en: {
    engine: "Engine", transmission: "Gearbox", drivetrain: "Drivetrain",
    steering: "Steering", braking: "Brakes", electrics: "Electrics",
    fuel: "Fuel system", high_voltage: "High-voltage system",
    self_diagnosis: "Electronic self-test",
  },
};

const ITEM_LABELS = {
  bg: {
    engine_self_test: "Двигател (сканиране)", transmission_self_test: "Кутия (сканиране)",
    idle_running: "Работа на празен ход", operation_idle: "Работа на празен ход",
    rocker_cover: "Капак на клапаните", head_gasket: "Гарнитура на глава",
    head_gasket_coolant: "Глава — теч на антифриз", cylinder_block: "Блок и картер",
    oil_level: "Ниво на маслото", water_pump: "Водна помпа", radiator: "Радиатор",
    coolant_level: "Ниво на антифриза", common_rail: "Common rail",
    oil_leak: "Теч на масло", fluid_level_condition: "Ниво и състояние на маслото",
    gear_selector: "Скоростен механизъм", clutch: "Съединител",
    cv_joint: "Каре (равноскоростен шарнир)", driveshaft_bearings: "Карданен вал и лагери",
    differential: "Диференциал", power_steering_leak: "Теч на хидравлично масло",
    steering_gear: "Кормилна рейка (вкл. MDPS)", steering_pump: "Помпа на кормилното",
    tie_rod_ball_joint: "Кормилни щанги и шарнири", steering_joints: "Кормилни съединения",
    high_pressure_hose: "Маркуч високо налягане",
    brake_master_cylinder: "Спирачна помпа — теч", brake_fluid_leak: "Теч на спирачна течност",
    brake_booster: "Спирачен усилвател", alternator_output: "Заряд на алтернатора",
    starter_motor: "Стартер", wiper_motor: "Мотор на чистачките",
    cabin_blower: "Вентилатор на купето", radiator_fan: "Перка на радиатора",
    window_motors: "Мотори на стъклата", fuel_leak: "Теч на гориво",
    charge_port_insulation: "Изолация на зарядния порт",
    traction_battery_isolation: "Изолация на тяговата батерия",
    hv_wiring: "Високоволтови кабели",
  },
  ro: {
    engine_self_test: "Motor (scanare)", transmission_self_test: "Cutie (scanare)",
    idle_running: "Funcționare în gol", operation_idle: "Funcționare în gol",
    rocker_cover: "Capac culbutori", head_gasket: "Garnitură de chiulasă",
    head_gasket_coolant: "Chiulasă — scurgere antigel", cylinder_block: "Bloc motor și baie de ulei",
    oil_level: "Nivel ulei", water_pump: "Pompă de apă", radiator: "Radiator",
    coolant_level: "Nivel antigel", common_rail: "Common rail",
    oil_leak: "Scurgere de ulei", fluid_level_condition: "Nivelul și starea uleiului",
    gear_selector: "Mecanism de schimbare", clutch: "Ambreiaj",
    cv_joint: "Articulație homocinetică", driveshaft_bearings: "Arbore cardanic și rulmenți",
    differential: "Diferențial", power_steering_leak: "Scurgere ulei servodirecție",
    steering_gear: "Casetă de direcție (incl. MDPS)", steering_pump: "Pompă servodirecție",
    tie_rod_ball_joint: "Bare de direcție și pivoți", steering_joints: "Articulații de direcție",
    high_pressure_hose: "Furtun de înaltă presiune",
    brake_master_cylinder: "Pompă centrală frână — scurgere",
    brake_fluid_leak: "Scurgere lichid de frână", brake_booster: "Servofrână",
    alternator_output: "Debit alternator", starter_motor: "Electromotor",
    wiper_motor: "Motor ștergătoare", cabin_blower: "Ventilator habitaclu",
    radiator_fan: "Ventilator radiator", window_motors: "Motoare geamuri",
    fuel_leak: "Scurgere de combustibil",
    charge_port_insulation: "Izolația portului de încărcare",
    traction_battery_isolation: "Izolația bateriei de tracțiune",
    hv_wiring: "Cablaj de înaltă tensiune",
  },
  en: {
    engine_self_test: "Engine (scan)", transmission_self_test: "Gearbox (scan)",
    idle_running: "Running at idle", operation_idle: "Running at idle",
    rocker_cover: "Rocker cover", head_gasket: "Head gasket",
    head_gasket_coolant: "Head gasket — coolant", cylinder_block: "Block and sump",
    oil_level: "Oil level", water_pump: "Water pump", radiator: "Radiator",
    coolant_level: "Coolant level", common_rail: "Common rail",
    oil_leak: "Oil leak", fluid_level_condition: "Fluid level and condition",
    gear_selector: "Gear selector", clutch: "Clutch",
    cv_joint: "CV joint", driveshaft_bearings: "Propshaft and bearings",
    differential: "Differential", power_steering_leak: "Power steering fluid leak",
    steering_gear: "Steering rack (incl. MDPS)", steering_pump: "Steering pump",
    tie_rod_ball_joint: "Track rods and ball joints", steering_joints: "Steering joints",
    high_pressure_hose: "High-pressure hose",
    brake_master_cylinder: "Master cylinder leak", brake_fluid_leak: "Brake fluid leak",
    brake_booster: "Brake servo", alternator_output: "Alternator output",
    starter_motor: "Starter motor", wiper_motor: "Wiper motor",
    cabin_blower: "Cabin blower", radiator_fan: "Radiator fan",
    window_motors: "Window motors", fuel_leak: "Fuel leak",
    charge_port_insulation: "Charge port insulation",
    traction_battery_isolation: "Traction battery isolation",
    hv_wiring: "High-voltage wiring",
  },
};

const COPY = {
  bg: { title: "Механична проверка", ok: "Добре", warn: "Леко просмукване",
        bad: "Установен проблем",
        clean: (n) => `${n} проверени точки, всички добре`,
        some: (n) => `${n} проверени точки`,
        note: "По данни от инспекционния лист на Encar." },
  ro: { title: "Verificare mecanică", ok: "În regulă", warn: "Ușoară transpirație",
        bad: "Problemă constatată",
        clean: (n) => `${n} puncte verificate, toate în regulă`,
        some: (n) => `${n} puncte verificate`,
        note: "Conform fișei de inspecție Encar." },
  en: { title: "Mechanical check", ok: "Fine", warn: "Slight seepage",
        bad: "Fault found",
        clean: (n) => `${n} points checked, all fine`,
        some: (n) => `${n} points checked`,
        note: "From Encar's inspection sheet." },
};

const ICONS = {
  ok: { Icon: CheckCircle2, cls: "text-emerald-600 dark:text-emerald-500" },
  warn: { Icon: AlertTriangle, cls: "text-amber-600 dark:text-amber-500" },
  bad: { Icon: XCircle, cls: "text-red-600 dark:text-red-500" },
};

export const MechChecks = ({ checks }) => {
  const { lang } = useApp();
  if (!checks?.available) return null;

  const S = SECTION_LABELS[lang] || SECTION_LABELS.en;
  const I = ITEM_LABELS[lang] || ITEM_LABELS.en;
  const c = COPY[lang] || COPY.en;

  return (
    <section
      data-testid="mech-checks"
      className="rounded-[16px] border border-border bg-card p-5 shadow-sm"
    >
      <div className="flex items-center gap-2">
        <Wrench className="h-[18px] w-[18px] text-muted-foreground" aria-hidden="true" />
        <h2 className="text-[14.5px] font-semibold text-foreground">{c.title}</h2>
      </div>

      <p data-testid="mech-checks-summary" className="mt-1 text-[12px] text-muted-foreground">
        {checks.clean ? c.clean(checks.checks) : c.some(checks.checks)}
      </p>

      <ul className="mt-3 flex flex-col">
        {checks.sections.map((sec) => {
          const { Icon, cls } = ICONS[sec.verdict] || ICONS.ok;
          return (
            <li
              key={sec.slug}
              data-testid={`mech-section-${sec.slug}`}
              className="border-b border-border/60 py-2 last:border-0"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-[13px] text-foreground">{S[sec.slug] || sec.slug}</span>
                <span className={`flex items-center gap-1.5 text-[12.5px] font-medium ${cls}`}>
                  <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                  {c[sec.verdict]}
                </span>
              </div>

              {sec.findings.length > 0 && (
                <ul className="mt-1 flex flex-col gap-0.5 pl-1">
                  {sec.findings.map((f, i) => (
                    <li
                      key={`${f.slug}-${i}`}
                      data-testid={`mech-finding-${f.slug}`}
                      className="flex items-baseline justify-between gap-3 text-[12px] text-muted-foreground"
                    >
                      <span>{I[f.slug] || f.slug}</span>
                      <span className={ICONS[f.status].cls}>{c[f.status]}</span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>

      <p className="mt-3 text-[11.5px] text-muted-foreground">{c.note}</p>
    </section>
  );
};

export default MechChecks;
