import { COMPANY } from "@/content/company";

/**
 * The site's legal documents, in all three languages.
 *
 * Written for this business specifically: we buy cars at Korean auction/dealer level, quote
 * one landed price, ship them by sea and deliver to the buyer's address. The documents say
 * exactly that, and nothing they cannot back up. They are a starting point drafted in good
 * faith, NOT legal advice — the owner should have a Bulgarian lawyer review them before
 * relying on them commercially, which the pages themselves say.
 */
const UPDATED = "2026-06-01";

const doc = (title, intro, sections) => ({ title, intro, sections, updated: UPDATED });

const BG = {
  terms: doc(
    "Общи условия",
    `Тези условия уреждат използването на ${COMPANY.site} и поръчката на автомобил чрез ${COMPANY.name}, ЕИК ${COMPANY.eik}.`,
    [
      ["Какво правим",
        [`Показваме автомобили, обявени за продажба в Южна Корея, преведени на български, румънски и английски.`,
         `Цената, която виждаш, е крайна прогнозна цена до твоя адрес: включва автомобила, морския транспорт, мито и ДДС, освен ако на страницата на обявата не е посочено друго.`]],
      ["Обявите не са наша собственост",
        [`Данните и снимките идват от корейския пазар и се обновяват периодично. Възможно е автомобил да бъде продаден или свален от продажба, преди да получим обновени данни.`,
         `Затова обява на сайта е покана за запитване, а не обвързваща оферта. Обвързваща цена получаваш в писмено потвърждение от нас.`]],
      ["Поръчка и плащане",
        [`След запитване потвърждаваме наличността, окончателната цена и срока, и издаваме документ за плащане. Договорът се счита сключен, когато потвърдим поръчката писмено.`,
         `Плащането се извършва по банков път към ${COMPANY.name}. Не приемаме плащания в брой за автомобили.`]],
      ["Срокове и доставка",
        [`Ориентировъчният срок от потвърдена поръчка до доставка е между 6 и 10 седмици и зависи от корабните разписания, пристанищните и митническите процедури.`,
         `Датите в раздел „Проследи автомобила“ са прогнозни. Последната стъпка — доставка до твоя адрес — се изчислява като приблизително седем дни след пристигане в европейското пристанище.`]],
      ["Състояние на автомобила",
        [`Автомобилите са употребявани. Показваме инспекционния доклад и историята, доколкото са налични от източника.`,
         `Употребяван автомобил може да има износване, което не е отразено в документите. При съмнение поискай допълнителна проверка преди да поръчаш.`]],
      ["Право на отказ",
        [`Ако си потребител по смисъла на българското законодателство, имаш законовите си права, включително право на отказ, когато то е приложимо за конкретната сделка.`,
         `Автомобил, поръчан и внесен по твоя изрична индивидуална заявка, може да попада в изключенията от правото на отказ. Ще ти посочим кое важи за твоята поръчка, преди да платиш.`]],
      ["Отговорност",
        [`Не отговаряме за забави, причинени от превозвачи, пристанища, митници или органи, извън нашия контрол, но те винаги ти се съобщават веднага щом ги узнаем.`,
         `Не отговаряме за косвени вреди, като пропуснати ползи или разходи за наем на друг автомобил.`]],
      ["Спорове",
        [`Прилага се българското право. Спорове се решават от компетентния български съд, освен ако задължителна потребителска норма не предвижда друго.`,
         `Можеш да се обърнеш и към Комисията за защита на потребителите или към платформата за онлайн решаване на спорове на Европейската комисия.`]],
      ["Контакт",
        [`Пиши ни на ${COMPANY.email}. Отговаряме в рамките на два работни дни.`]],
    ]
  ),
  privacy: doc(
    "Политика за поверителност",
    `${COMPANY.name}, ЕИК ${COMPANY.eik}, е администратор на личните данни, събирани през ${COMPANY.site}.`,
    [
      ["Какво събираме",
        [`Профил: имейл, име (ако го попълниш) и парола, съхранявана само като необратим хеш.`,
         `Адрес за доставка и фактуриране: име, адрес, град, пощенски код, държава и телефон — само ако ги въведеш. Използваме ги, за да доставим автомобила и да издадем документи.`,
         `Запитвания: съобщението и данните за контакт, които ни изпращаш.`,
         `Проследяване: номерата на товарителници, които търсиш, за да ти покажем статуса на пратката.`]],
      ["Предпочитания в браузъра ти",
        [`Кои марки и модели разглеждаш се записва в бисквитка на твоето устройство със срок 90 дни и се използва, за да ти показваме подходящи автомобили.`,
         `Този профил не се съхранява при нас — изпраща се с конкретната заявка и не се свързва с име или имейл. Изтриването на бисквитките го премахва напълно.`]],
      ["Защо ги обработваме",
        [`За да изпълним договора с теб — поръчка, внос, доставка и поддръжка на профила.`,
         `Заради законови задължения — счетоводство, данъци и митнически документи.`,
         `Със твоето съгласие — персонализирани предложения и бисквитки, които не са строго необходими.`]],
      ["С кого ги споделяме",
        [`Спедитори, превозвачи, митнически агенти и корейски партньори, доколкото е нужно за конкретната покупка.`,
         `Доставчици на услуги, които поддържат сайта: хостинг, доставка на имейли и услуга за проследяване на контейнери.`,
         `Държавни органи, когато законът го изисква. Не продаваме лични данни.`]],
      ["Колко дълго ги пазим",
        [`Данни по сделка — 10 години, както изисква счетоводното и данъчното законодателство.`,
         `Профил — докато го поддържаш активен. При изтриване премахваме профила и адреса, освен документите, които сме длъжни да пазим.`]],
      ["Твоите права",
        [`Достъп, коригиране, изтриване, ограничаване, преносимост и възражение срещу обработване, както и оттегляне на съгласие по всяко време.`,
         `Пиши на ${COMPANY.email}. Ако смяташ, че нарушаваме правата ти, можеш да подадеш жалба до Комисията за защита на личните данни.`]],
      ["Сигурност",
        [`Връзката със сайта е криптирана. Паролите се съхраняват хеширани, а достъпът до данните е ограничен до хората, които го изискват за работата си.`]],
      ["Бележка",
        [`Този текст е изготвен добросъвестно и не замества юридическа консултация. Преди да разчиташ на него търговски, дай го за преглед на адвокат.`]],
    ]
  ),
  cookies: doc(
    "Политика за бисквитките",
    `Използваме малко бисквитки и ти казваме точно за какво.`,
    [
      ["Необходими",
        [`Език и валута, тъмна или светла тема, вход в профила и защита на формите. Без тях сайтът не работи и не искаме съгласие за тях.`]],
      ["Предпочитания (със съгласие)",
        [`ab_taste — какви автомобили разглеждаш, за да подредим предложенията. Срок 90 дни.`,
         `ab_vid — анонимен идентификатор на браузъра, свързан със същия профил на предпочитания. Срок 90 дни.`,
         `ab_track — номерата на товарителници, които вече си проверявал, за да не ги търсиш отново. Срок 90 дни.`]],
      ["Как да ги откажеш",
        [`Откажи ги в лентата за бисквитки при първото посещение или изтрий бисквитките за сайта от настройките на браузъра си.`,
         `Ако откажеш, сайтът работи напълно — просто не подреждаме предложения по твоите интереси.`]],
      ["Външни бисквитки",
        [`Не използваме рекламни мрежи и не вграждаме проследяващи пиксели на трети страни.`]],
    ]
  ),
  contact: doc(
    "Контакт и данни за фирмата",
    `Сайтът се управлява от ${COMPANY.name}.`,
    [
      ["Фирмени данни",
        [`Наименование: ${COMPANY.name}`, `ЕИК: ${COMPANY.eik}`, `Държава на регистрация: България`]],
      ["Връзка с нас",
        [`Имейл: ${COMPANY.email}`, `Отговаряме в рамките на два работни дни.`]],
      ["Жалби",
        [`Ако не сме решили въпроса ти, можеш да се обърнеш към Комисията за защита на потребителите.`]],
    ]
  ),
};

const RO = {
  terms: doc(
    "Termeni și condiții",
    `Acești termeni reglementează folosirea site-ului ${COMPANY.site} și comanda unei mașini prin ${COMPANY.name}, cod unic ${COMPANY.eik}.`,
    [
      ["Ce facem",
        [`Afișăm mașini scoase la vânzare în Coreea de Sud, traduse în bulgară, română și engleză.`,
         `Prețul afișat este prețul final estimat până la adresa ta: mașina, transportul maritim, taxele vamale și TVA, dacă pagina anunțului nu spune altfel.`]],
      ["Anunțurile nu ne aparțin",
        [`Datele și fotografiile provin din piața coreeană și se actualizează periodic. O mașină poate fi vândută înainte să primim date noi.`,
         `De aceea un anunț este o invitație la cerere, nu o ofertă obligatorie. Prețul obligatoriu îl primești în confirmarea noastră scrisă.`]],
      ["Comandă și plată",
        [`După cerere confirmăm disponibilitatea, prețul final și termenul, apoi emitem documentul de plată. Contractul se încheie când confirmăm comanda în scris.`,
         `Plata se face prin transfer bancar către ${COMPANY.name}. Nu acceptăm numerar pentru mașini.`]],
      ["Termene și livrare",
        [`Termenul orientativ de la comanda confirmată până la livrare este de 6-10 săptămâni și depinde de orarele navelor și de procedurile portuare și vamale.`,
         `Datele din „Urmărește mașina” sunt estimări. Ultimul pas — livrarea la adresa ta — se calculează la aproximativ șapte zile după sosirea în portul european.`]],
      ["Starea mașinii",
        [`Mașinile sunt second-hand. Afișăm raportul de inspecție și istoricul, în măsura în care sursa le pune la dispoziție.`,
         `O mașină folosită poate avea uzură care nu apare în documente. Dacă ai dubii, cere o verificare suplimentară înainte de comandă.`]],
      ["Dreptul de retragere",
        [`Dacă ești consumator, îți păstrezi drepturile legale, inclusiv dreptul de retragere atunci când se aplică tranzacției tale.`,
         `O mașină adusă la cererea ta individuală expresă poate intra în excepțiile de la dreptul de retragere. Îți spunem ce se aplică înainte de plată.`]],
      ["Răspundere",
        [`Nu răspundem pentru întârzieri provocate de transportatori, porturi, vamă sau autorități, dar te informăm imediat ce le aflăm.`,
         `Nu răspundem pentru prejudicii indirecte, precum profit nerealizat sau costul închirierii altei mașini.`]],
      ["Litigii",
        [`Se aplică legea bulgară. Litigiile se soluționează de instanța bulgară competentă, dacă o normă imperativă de protecție a consumatorului nu prevede altfel.`,
         `Poți folosi și platforma europeană de soluționare online a litigiilor.`]],
      ["Contact",
        [`Scrie-ne la ${COMPANY.email}. Răspundem în două zile lucrătoare.`]],
    ]
  ),
  privacy: doc(
    "Politica de confidențialitate",
    `${COMPANY.name}, cod unic ${COMPANY.eik}, este operatorul datelor colectate prin ${COMPANY.site}.`,
    [
      ["Ce colectăm",
        [`Cont: e-mail, nume (dacă îl completezi) și parola, păstrată doar ca hash ireversibil.`,
         `Adresa de livrare și facturare: nume, adresă, oraș, cod poștal, țară și telefon — numai dacă le introduci. Le folosim pentru livrare și pentru documente.`,
         `Cereri: mesajul și datele de contact pe care ni le trimiți.`,
         `Urmărire: numerele de conosament pe care le cauți, ca să îți arătăm starea transportului.`]],
      ["Preferințele din browserul tău",
        [`Mărcile și modelele pe care le deschizi se rețin într-un cookie pe dispozitivul tău, valabil 90 de zile, ca să îți arătăm mașini potrivite.`,
         `Acest profil nu se stochează la noi — este trimis cu cererea respectivă și nu este legat de nume sau e-mail. Ștergerea cookie-urilor îl elimină complet.`]],
      ["De ce prelucrăm datele",
        [`Pentru executarea contractului — comandă, import, livrare și administrarea contului.`,
         `Pentru obligații legale — contabilitate, taxe și documente vamale.`,
         `Cu consimțământul tău — recomandări personalizate și cookie-uri care nu sunt strict necesare.`]],
      ["Cu cine le împărtășim",
        [`Case de expediții, transportatori, agenți vamali și parteneri coreeni, cât este necesar pentru achiziția respectivă.`,
         `Furnizori care țin site-ul în funcțiune: găzduire, livrare de e-mail și serviciul de urmărire a containerelor.`,
         `Autorități, când legea o cere. Nu vindem date personale.`]],
      ["Cât le păstrăm",
        [`Datele tranzacției — 10 ani, conform legislației contabile și fiscale.`,
         `Contul — cât timp îl păstrezi activ. La ștergere eliminăm contul și adresa, cu excepția documentelor pe care suntem obligați să le păstrăm.`]],
      ["Drepturile tale",
        [`Acces, rectificare, ștergere, restricționare, portabilitate și opoziție, plus retragerea consimțământului oricând.`,
         `Scrie la ${COMPANY.email}. Poți depune plângere și la autoritatea de protecție a datelor.`]],
      ["Securitate",
        [`Conexiunea este criptată, parolele sunt păstrate ca hash, iar accesul la date este limitat la persoanele care au nevoie de el.`]],
      ["Notă",
        [`Textul este redactat cu bună-credință și nu înlocuiește consultanța juridică. Cere avizul unui avocat înainte să te bazezi comercial pe el.`]],
    ]
  ),
  cookies: doc(
    "Politica de cookie-uri",
    `Folosim puține cookie-uri și îți spunem exact pentru ce.`,
    [
      ["Necesare",
        [`Limba și moneda, tema, autentificarea și protecția formularelor. Fără ele site-ul nu funcționează, așa că nu cerem consimțământ pentru ele.`]],
      ["Preferințe (cu consimțământ)",
        [`ab_taste — ce mașini deschizi, ca să ordonăm recomandările. 90 de zile.`,
         `ab_vid — identificator anonim al browserului, legat de același profil de preferințe. 90 de zile.`,
         `ab_track — numerele de conosament pe care le-ai verificat deja. 90 de zile.`]],
      ["Cum le refuzi",
        [`Refuză-le din bara de cookie-uri la prima vizită sau șterge cookie-urile site-ului din browser.`,
         `Dacă refuzi, site-ul funcționează complet — doar nu ordonăm recomandările după interesele tale.`]],
      ["Cookie-uri externe",
        [`Nu folosim rețele de publicitate și nu inserăm pixeli de urmărire ai terților.`]],
    ]
  ),
  contact: doc(
    "Contact și date despre firmă",
    `Site-ul este administrat de ${COMPANY.name}.`,
    [
      ["Date despre firmă",
        [`Denumire: ${COMPANY.name}`, `Cod unic: ${COMPANY.eik}`, `Țara de înregistrare: Bulgaria`]],
      ["Contact",
        [`E-mail: ${COMPANY.email}`, `Răspundem în două zile lucrătoare.`]],
      ["Reclamații",
        [`Dacă nu am rezolvat problema, te poți adresa autorității de protecție a consumatorului.`]],
    ]
  ),
};

const EN = {
  terms: doc(
    "Terms of service",
    `These terms cover the use of ${COMPANY.site} and ordering a car through ${COMPANY.name}, company number ${COMPANY.eik}.`,
    [
      ["What we do",
        [`We show cars offered for sale in South Korea, translated into Bulgarian, Romanian and English.`,
         `The price you see is the estimated final price to your address: the car, sea freight, customs duty and VAT, unless the listing page says otherwise.`]],
      ["The listings are not ours",
        [`Data and photos come from the Korean market and are refreshed periodically. A car can be sold before we receive updated data.`,
         `A listing is therefore an invitation to enquire, not a binding offer. A binding price comes in our written confirmation.`]],
      ["Ordering and payment",
        [`After your enquiry we confirm availability, the final price and the lead time, then issue the payment document. The contract is formed when we confirm your order in writing.`,
         `Payment is by bank transfer to ${COMPANY.name}. We do not accept cash for vehicles.`]],
      ["Lead times and delivery",
        [`From a confirmed order to delivery usually takes 6 to 10 weeks, depending on sailing schedules and on port and customs procedures.`,
         `Dates on the "Track my vehicle" page are estimates. The final step — delivery to your address — is calculated as roughly seven days after arrival at the European port.`]],
      ["Condition of the car",
        [`The cars are used. We show the inspection report and the history as far as the source makes them available.`,
         `A used car can have wear that the paperwork does not record. If in doubt, ask for an extra inspection before you order.`]],
      ["Right of withdrawal",
        [`If you are a consumer, you keep your statutory rights, including the right of withdrawal where it applies to your transaction.`,
         `A car imported on your express individual instruction may fall within the exceptions to that right. We will tell you which applies before you pay.`]],
      ["Liability",
        [`We are not liable for delays caused by carriers, ports, customs or authorities outside our control, but we always pass them on as soon as we learn of them.`,
         `We are not liable for indirect losses such as lost profit or the cost of hiring another car.`]],
      ["Disputes",
        [`Bulgarian law applies. Disputes go to the competent Bulgarian court, unless a mandatory consumer rule says otherwise.`,
         `You may also use the European Commission's online dispute resolution platform.`]],
      ["Contact",
        [`Write to ${COMPANY.email}. We answer within two working days.`]],
    ]
  ),
  privacy: doc(
    "Privacy policy",
    `${COMPANY.name}, company number ${COMPANY.eik}, is the controller of the personal data collected through ${COMPANY.site}.`,
    [
      ["What we collect",
        [`Account: your email, your name if you give it, and your password, kept only as an irreversible hash.`,
         `Delivery and billing address: name, street, city, post code, country and phone — only if you enter them. We use them to deliver the car and to raise documents.`,
         `Enquiries: the message and contact details you send us.`,
         `Tracking: the bill of lading numbers you look up, so we can show you the shipment.`]],
      ["Preferences kept in your browser",
        [`Which makes and models you browse is stored in a cookie on your own device for 90 days and used to show you relevant cars.`,
         `That profile is not stored on our side — it is sent with the request that needs it and is not tied to a name or an email. Clearing your cookies removes it completely.`]],
      ["Why we process it",
        [`To perform our contract with you — ordering, importing, delivering and running your account.`,
         `To meet legal duties — accounting, tax and customs paperwork.`,
         `With your consent — personalised suggestions and any cookie that is not strictly necessary.`]],
      ["Who we share it with",
        [`Freight forwarders, carriers, customs agents and Korean partners, as far as your purchase requires.`,
         `Providers that keep the site running: hosting, email delivery and the container tracking service.`,
         `Authorities, where the law requires it. We do not sell personal data.`]],
      ["How long we keep it",
        [`Transaction records for 10 years, as accounting and tax law require.`,
         `Your account for as long as you keep it. On deletion we remove the account and the address, apart from documents we must retain.`]],
      ["Your rights",
        [`Access, correction, erasure, restriction, portability and objection, and you can withdraw consent at any time.`,
         `Write to ${COMPANY.email}. You can also complain to the Bulgarian data protection authority.`]],
      ["Security",
        [`Traffic is encrypted, passwords are hashed, and access to data is limited to the people who need it for their work.`]],
      ["Note",
        [`This text was drafted in good faith and is not legal advice. Have a lawyer review it before you rely on it commercially.`]],
    ]
  ),
  cookies: doc(
    "Cookie policy",
    `We use few cookies, and we tell you exactly what each one is for.`,
    [
      ["Necessary",
        [`Language and currency, light or dark theme, staying signed in and protecting forms. The site does not work without them, so we do not ask for consent for these.`]],
      ["Preferences (with consent)",
        [`ab_taste — which cars you browse, so we can order the suggestions. 90 days.`,
         `ab_vid — an anonymous browser identifier tied to that same preference profile. 90 days.`,
         `ab_track — the bill of lading numbers you have already looked up. 90 days.`]],
      ["How to refuse them",
        [`Decline in the cookie bar on your first visit, or clear this site's cookies in your browser settings.`,
         `If you decline, the site still works fully — we simply do not order suggestions around your interests.`]],
      ["Third-party cookies",
        [`We use no advertising networks and embed no third-party tracking pixels.`]],
    ]
  ),
  contact: doc(
    "Contact and company details",
    `This site is operated by ${COMPANY.name}.`,
    [
      ["Company details",
        [`Name: ${COMPANY.name}`, `Company number: ${COMPANY.eik}`, `Country of registration: Bulgaria`]],
      ["Reach us",
        [`Email: ${COMPANY.email}`, `We answer within two working days.`]],
      ["Complaints",
        [`If we have not resolved your issue, you can turn to the Bulgarian consumer protection commission.`]],
    ]
  ),
};

const DOCS = { bg: BG, ro: RO, en: EN };

export function legalDoc(lang, slug) {
  const table = DOCS[lang] || DOCS.bg;
  return table[slug] || table.terms;
}
