import { COMPANY } from "@/content/company";

/**
 * Help pages: the questions buyers actually ask, and what the price is made of.
 *
 * Same shape as the legal documents so `LegalPage` renders them unchanged. Deliberately
 * conservative: every number here is either fixed by us (the deposit) or described as a
 * range, because shipping and duty move with the car and the calendar.
 */
const UPDATED = "2026-06-01";

const doc = (title, intro, sections) => ({ title, intro, sections, updated: UPDATED });

// Same lazy build as the legal documents: the company details are editable in the admin.
function build() {

const BG = {
  faq: doc(
    "Често задавани въпроси",
    "Най-честите въпроси за поръчка на автомобил от Корея. Ако нещо липсва, пиши ни.",
    [
      ["Цената на сайта крайна ли е?",
        ["Да, освен ако на страницата на обявата не е посочено друго. Показваната цена включва автомобила, морския транспорт, митото и ДДС до твоя адрес.",
         "Обвързваща цена получаваш в писмено потвърждение, след като проверим наличността — обявите идват от корейския пазар и се обновяват периодично."]],
      ["Колко време отнема доставката?",
        ["Между 6 и 10 седмици от потвърдена поръчка. Зависи от корабните разписания, пристанищните операции и митническите процедури.",
         "След като автомобилът бъде натоварен, следиш кораба и всяка стъпка в „Проследи автомобила“."]],
      ["Как задържам автомобил, който ми е харесал?",
        ["С депозит от 10% от цената на автомобила. С него ние купуваме автомобила за вас, затова депозитът не се възстановява, ако се откажете. След като платите остатъка по банков път, ви връщаме депозита и задържаме 300 € комисиона, която вече е включена в крайната цена. Ако ние не успеем да доставим автомобила, получавате всичко обратно.",
         "Плащането минава през Stripe — картовите данни се обработват от Stripe и никога не достигат наш сървър."]],
      ["Мога ли да видя автомобила преди да платя?",
        ["Не на място, но показваме инспекционния доклад, историята на щетите и всички снимки от обявата.",
         "При съмнение поискай допълнителна проверка, преди да поръчаш — организираме я, докато автомобилът е още в Корея."]],
      ["Какво става, ако автомобилът вече е продаден?",
        ["Понякога автомобил се продава, преди да получим обновени данни. В такъв случай ти казваме веднага и предлагаме най-близките налични алтернативи.",
         "Ако вече е платен депозит за такъв автомобил, той се възстановява напълно."]],
      ["Регистрацията в България включена ли е?",
        ["Не. Цената стига до твоя адрес с платени мито и ДДС. Регистрацията и данъкът върху превозното средство се извършват от теб.",
         "Даваме ти всички документи, необходими за регистрация."]],
      ["Автомобилите нови ли са?",
        ["Не, всички са употребявани. Употребяван автомобил може да има износване, което не е отразено в документите."]],
    ]
  ),
  fees: doc(
    "Такси и комисионни",
    `Какво плащаш и на кого. ${COMPANY.name} печели от една комисионна, включена в показаната цена — без скрити добавки в края.`,
    [
      ["Какво включва показаната цена",
        ["Стойността на автомобила в Корея.",
         "Вътрешен транспорт до пристанището и експортни формалности.",
         "Морски транспорт до европейско пристанище.",
         "Мито и ДДС при вноса.",
         "Транспорт от пристанището до твоя адрес.",
         "Нашата комисионна за подбор, проверка и организация."]],
      ["Депозит за резервация",
        ["10% от цената на автомобила. Не се възстановява при отказ — с него купуваме автомобила. Връща се след плащането на остатъка, като задържаме 300 € комисиона, която вече е включена в крайната цена.",
         "Възстановява се напълно, ако автомобилът се окаже недостъпен или ако не потвърдим поръчката."]],
      ["Какво не е включено",
        ["Регистрация в страната ти и местен данък върху превозното средство.",
         "Ремонти или подготовка след доставка.",
         "Складови такси, ако автомобилът не бъде приет в договорения срок след пристигане."]],
      ["Плащане",
        ["Депозитът се плаща с карта през Stripe. Остатъкът — по банков път към сметката на дружеството.",
         "Не приемаме плащания в брой за автомобили."]],
    ]
  ),
};

const RO = {
  faq: doc(
    "Întrebări frecvente",
    "Cele mai frecvente întrebări despre comandarea unui automobil din Coreea. Dacă lipsește ceva, scrie-ne.",
    [
      ["Prețul afișat este final?",
        ["Da, dacă pagina anunțului nu spune altfel. Prețul afișat include automobilul, transportul maritim, taxa vamală și TVA până la adresa ta.",
         "Prețul obligatoriu îl primești în confirmarea scrisă, după ce verificăm disponibilitatea — anunțurile vin din piața coreeană și se actualizează periodic."]],
      ["Cât durează livrarea?",
        ["Între 6 și 10 săptămâni de la comanda confirmată, în funcție de orarele navelor, operațiunile portuare și procedurile vamale.",
         "După încărcare urmărești nava și fiecare etapă în „Urmărește mașina”."]],
      ["Cum rețin un automobil care mi-a plăcut?",
        ["Cu un depozit de 10% din prețul automobilului. Cu el cumpărăm automobilul pentru tine, de aceea depozitul nu se restituie dacă te retragi. După ce plătești restul prin transfer bancar, îți returnăm depozitul și reținem 300 € comision, care este deja inclus în prețul final. Dacă noi nu reușim să livrăm automobilul, primești totul înapoi.",
         "Plata trece prin Stripe — datele cardului sunt procesate de Stripe și nu ajung niciodată pe serverul nostru."]],
      ["Pot vedea automobilul înainte de plată?",
        ["Nu la fața locului, dar arătăm raportul de inspecție, istoricul daunelor și toate fotografiile din anunț.",
         "Dacă ai dubii, cere o verificare suplimentară înainte de a comanda — o organizăm cât timp automobilul este încă în Coreea."]],
      ["Ce se întâmplă dacă automobilul este deja vândut?",
        ["Uneori un automobil se vinde înainte să primim date actualizate. În acest caz îți spunem imediat și propunem cele mai apropiate alternative disponibile.",
         "Dacă a fost deja plătit un depozit, acesta se returnează integral."]],
      ["Înmatricularea este inclusă?",
        ["Nu. Prețul ajunge la adresa ta cu taxa vamală și TVA plătite. Înmatricularea și impozitul local le faci tu.",
         "Îți dăm toate documentele necesare pentru înmatriculare."]],
      ["Automobilele sunt noi?",
        ["Nu, toate sunt rulate. Un automobil rulat poate avea uzură care nu apare în documente."]],
    ]
  ),
  fees: doc(
    "Taxe și comisioane",
    `Ce plătești și cui. ${COMPANY.name} câștigă dintr-un singur comision, inclus în prețul afișat — fără adaosuri ascunse la final.`,
    [
      ["Ce include prețul afișat",
        ["Valoarea automobilului în Coreea.",
         "Transportul interior până în port și formalitățile de export.",
         "Transportul maritim până în portul european.",
         "Taxa vamală și TVA la import.",
         "Transportul din port până la adresa ta.",
         "Comisionul nostru pentru selecție, verificare și organizare."]],
      ["Depozit de rezervare",
        ["10% din prețul automobilului. Nu se restituie dacă te retragi — cu el cumpărăm automobilul. Se returnează după plata restului, mai puțin 300 € comision, care este deja inclus în prețul final.",
         "Se returnează integral dacă automobilul nu mai este disponibil sau dacă nu confirmăm comanda."]],
      ["Ce nu este inclus",
        ["Înmatricularea în țara ta și impozitul local pe vehicul.",
         "Reparații sau pregătire după livrare.",
         "Taxe de depozitare, dacă automobilul nu este preluat în termenul convenit după sosire."]],
      ["Plata",
        ["Depozitul se plătește cu cardul prin Stripe. Restul — prin transfer bancar în contul firmei.",
         "Nu acceptăm plăți în numerar pentru automobile."]],
    ]
  ),
};

const EN = {
  faq: doc(
    "Frequently asked questions",
    "The questions buyers ask most about ordering a car from Korea. If something is missing, write to us.",
    [
      ["Is the price on the site the final price?",
        ["Yes, unless the listing page says otherwise. The price shown covers the car, sea freight, duty and VAT to your address.",
         "A binding price comes in our written confirmation, once we have checked availability — listings come from the Korean market and are refreshed periodically."]],
      ["How long does delivery take?",
        ["Between 6 and 10 weeks from a confirmed order, depending on sailing schedules, port operations and customs.",
         "Once the car is loaded you follow the ship and every step under \u201cTrack my vehicle\u201d."]],
      ["How do I hold a car I like?",
        ["With a deposit of 10% of the car's price. We buy the car for you with it, so the deposit is not refundable if you change your mind. Once you pay the balance by bank transfer we return the deposit and keep €300 as our commission, which is already included in the final price. If we cannot deliver the car, you get everything back.",
         "Payment goes through Stripe — card details are handled by Stripe and never reach our server."]],
      ["Can I see the car before paying?",
        ["Not in person, but we show the inspection report, the damage history and every photo from the listing.",
         "If anything is unclear, ask for an extra inspection before you order — we arrange it while the car is still in Korea."]],
      ["What happens if the car is already sold?",
        ["Sometimes a car sells before we receive refreshed data. We tell you straight away and offer the closest cars still available.",
         "If a deposit was already paid on that car, it is refunded in full."]],
      ["Is registration included?",
        ["No. The price reaches your address with duty and VAT paid. Registration and local vehicle tax are yours to do.",
         "We hand over every document you need to register the car."]],
      ["Are the cars new?",
        ["No, they are all used. A used car can carry wear that the paperwork does not record."]],
    ]
  ),
  fees: doc(
    "Fees and commissions",
    `What you pay and to whom. ${COMPANY.name} earns one commission, already inside the price you see — nothing is added at the end.`,
    [
      ["What the price on the site covers",
        ["The value of the car in Korea.",
         "Inland transport to the port and export formalities.",
         "Sea freight to a European port.",
         "Import duty and VAT.",
         "Transport from the port to your address.",
         "Our commission for sourcing, checking and organising the job."]],
      ["Reservation deposit",
        ["10% of the car's price. Not refundable if you withdraw — we buy the car with it. Returned once you pay the balance, less €300 commission, which is already included in the final price.",
         "Refunded in full if the car turns out to be unavailable, or if we do not confirm the order."]],
      ["What is not included",
        ["Registration in your country and local vehicle tax.",
         "Repairs or preparation after delivery.",
         "Storage charges, if the car is not collected within the agreed window after arrival."]],
      ["Paying",
        ["The deposit is paid by card through Stripe. The balance goes by bank transfer to the company account.",
         "We do not take cash for cars."]],
    ]
  ),
};

return { bg: BG, ro: RO, en: EN };
}

let cache = null;
let cacheKey = "";

function docs() {
  const key = JSON.stringify(COMPANY);
  if (!cache || cacheKey !== key) {
    cache = build();
    cacheKey = key;
  }
  return cache;
}

export function helpDoc(lang, slug) {
  const DOCS = docs();
  return (DOCS[lang] || DOCS.bg)[slug] || null;
}
