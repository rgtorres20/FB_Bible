/* Gabbs Glamour demo: the shared demo store.
 *
 * Every page reads and writes one object in localStorage, so a change on the
 * admin page (block off time, ban a client, add a coupon) shows up on the
 * booking page in the same browser. This is a mockup: nothing is sent
 * anywhere, and "Reset demo" on the admin page restores the seed.
 */
(function () {
  "use strict";
  var KEY = "gg_demo_v1";

  // Real services and prices from Gabby's current booking page (Nov 2026).
  var SERVICES = [
    { id: "new", name: "New Client Full Set", kind: "full", minutes: 180, price: null, note: "First visit. Includes consultation. Price set at consultation." },
    { id: "wet", name: "Wet Set", kind: "full", minutes: 150, price: 85, note: "Closed, narrow fans: the fresh-mascara look." },
    { id: "hybrid", name: "Hybrid", kind: "full", minutes: 150, price: 90, note: "Classic and volume blended for length and light fullness." },
    { id: "volume", name: "Volume", kind: "full", minutes: 165, price: 100, note: "Handmade fans for a full, fluffy look." },
    { id: "anime", name: "Anime / Manga", kind: "full", minutes: 165, price: 105, note: "Bold spikes with soft volume between." },
    { id: "mega", name: "Mega Volume", kind: "full", minutes: 180, price: 110, note: "Maximum density: a bold strip-lash effect." },
    { id: "wet-fill", name: "Wet Set Refill", kind: "refill", minutes: 90, price: 60, note: "At least 50% of lashes remaining." },
    { id: "hybrid-fill", name: "Hybrid Refill", kind: "refill", minutes: 90, price: 60, note: "At least 50% of lashes remaining." },
    { id: "volume-fill", name: "Volume Refill", kind: "refill", minutes: 90, price: 65, note: "At least 50% of lashes remaining." },
    { id: "anime-fill", name: "Anime / Manga Refill", kind: "refill", minutes: 90, price: 75, note: "At least 50% of lashes remaining." },
    { id: "mega-fill", name: "Mega Volume Refill", kind: "refill", minutes: 100, price: 75, note: "Within 14 days of your last appointment." },
    { id: "removal", name: "Removal", kind: "other", minutes: 30, price: 20, note: "Safe, gentle removal." }
  ];

  // Weekly hours, 0 = Sunday. Times are "HH:MM" 24h. Evenings carry the fee.
  var HOURS = {
    0: null,
    1: null,
    2: { open: "09:00", close: "21:00" },
    3: { open: "09:00", close: "17:00" },
    4: { open: "09:00", close: "21:00" },
    5: { open: "09:00", close: "17:00" },
    6: { open: "08:00", close: "12:00" }
  };
  var AFTER_HOURS_FROM = "17:30";
  var AFTER_HOURS_FEE = 10;
  var DEPOSIT = 30;
  var SLOT_STEP = 30; // minutes between offered start times

  function iso(d) {
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + m + "-" + day;
  }
  function addDays(n) { var d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() + n); return d; }
  function nextOpen(after) {
    for (var i = after; i < after + 14; i++) { if (HOURS[addDays(i).getDay()]) return iso(addDays(i)); }
    return iso(addDays(after));
  }

  // Demo clients and bookings. Names are clearly sample names.
  function seed() {
    var d1 = nextOpen(1), d2 = nextOpen(2), d3 = nextOpen(4);
    return {
      version: 1,
      clients: [
        { id: "c1", name: "Sample Client A", phone: "5550100001", email: "a@example.com", consentSignedAt: "2026-10-02", noShows: 0, banned: false, note: "" },
        { id: "c2", name: "Sample Client B", phone: "5550100002", email: "b@example.com", consentSignedAt: "2026-08-15", noShows: 2, banned: false, note: "Two no-shows in October." },
        { id: "c3", name: "Sample Client C", phone: "5550100003", email: "c@example.com", consentSignedAt: "2026-05-20", noShows: 3, banned: true, note: "Banned: three no-shows." }
      ],
      bookings: [
        { id: "b1", clientId: "c1", serviceId: "volume-fill", date: d1, start: "10:00", status: "confirmed", deposit: "apple_pay", depositPaid: true, coupon: null, total: 65 },
        { id: "b2", clientId: "c2", serviceId: "hybrid", date: d2, start: "13:00", status: "confirmed", deposit: "zelle", depositPaid: false, coupon: "WELCOME10", total: 80 },
        { id: "b3", clientId: "c1", serviceId: "removal", date: d3, start: "09:00", status: "confirmed", deposit: "cash_app", depositPaid: true, coupon: null, total: 20 }
      ],
      // Blocks: one-off ranges, whole days, or weekly repeats.
      blocks: [
        { id: "k1", type: "weekly", weekday: 3, start: "12:00", end: "13:00", reason: "Lunch" }
      ],
      coupons: [
        { code: "WELCOME10", type: "amount", value: 10, newOnly: true, expires: "2026-12-31", maxUses: 50, uses: 1, active: true },
        { code: "HOLIDAY15", type: "percent", value: 15, newOnly: false, expires: "2026-12-24", maxUses: 20, uses: 0, active: true }
      ],
      nextId: 100
    };
  }

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      if (raw) { var s = JSON.parse(raw); if (s && s.version === 1) return s; }
    } catch (e) { /* private window or blocked storage: fall through to the seed */ }
    return seed();
  }
  function save(state) {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* demo still works for this page view */ }
  }
  function reset() { var s = seed(); save(s); return s; }
  function newId(state, prefix) { state.nextId = (state.nextId || 100) + 1; return prefix + state.nextId; }

  function toMin(t) { var p = t.split(":"); return Number(p[0]) * 60 + Number(p[1]); }
  function fromMin(m) { return String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0"); }
  function label(t) {
    var m = toMin(t), h = Math.floor(m / 60), mm = String(m % 60).padStart(2, "0");
    return ((h + 11) % 12 + 1) + ":" + mm + (h < 12 ? " AM" : " PM");
  }
  function service(id) { for (var i = 0; i < SERVICES.length; i++) if (SERVICES[i].id === id) return SERVICES[i]; return null; }
  function weekday(dateIso) { var p = dateIso.split("-"); return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2])).getDay(); }

  function busyRanges(state, dateIso) {
    var out = [], wd = weekday(dateIso);
    state.bookings.forEach(function (b) {
      if (b.date === dateIso && b.status !== "canceled") {
        var s = service(b.serviceId); var st = toMin(b.start);
        out.push([st, st + (s ? s.minutes : 60)]);
      }
    });
    state.blocks.forEach(function (k) {
      if (k.type === "day" && k.date === dateIso) out.push([0, 24 * 60]);
      if (k.type === "range" && k.date === dateIso) out.push([toMin(k.start), toMin(k.end)]);
      if (k.type === "weekly" && k.weekday === wd) out.push([toMin(k.start), toMin(k.end)]);
    });
    return out;
  }

  // Start times a client can book: inside hours, clear of bookings and blocks.
  function availableSlots(state, dateIso, serviceId) {
    var h = HOURS[weekday(dateIso)], s = service(serviceId);
    if (!h || !s) return [];
    var busy = busyRanges(state, dateIso), out = [];
    // Today: never offer a start time that has already passed.
    var now = new Date(), first = toMin(h.open);
    if (dateIso === iso(now)) first = Math.max(first, now.getHours() * 60 + now.getMinutes() + 60);
    for (var t = first; t + s.minutes <= toMin(h.close); t += SLOT_STEP) {
      var end = t + s.minutes, clash = false;
      for (var i = 0; i < busy.length; i++) { if (t < busy[i][1] && end > busy[i][0]) { clash = true; break; } }
      if (!clash) out.push(fromMin(t));
    }
    return out;
  }
  function isAfterHours(start) { return toMin(start) >= toMin(AFTER_HOURS_FROM); }

  function findClient(state, phone, email) {
    var p = String(phone || "").replace(/\D/g, ""), e = String(email || "").trim().toLowerCase();
    for (var i = 0; i < state.clients.length; i++) {
      var c = state.clients[i];
      if ((p && c.phone === p) || (e && c.email.toLowerCase() === e)) return c;
    }
    return null;
  }
  function isBanned(state, phone, email) { var c = findClient(state, phone, email); return !!(c && c.banned); }
  function consentCurrent(client) {
    if (!client || !client.consentSignedAt) return false;
    var signed = new Date(client.consentSignedAt + "T00:00:00");
    return Date.now() - signed.getTime() < 365 * 24 * 3600 * 1000;
  }

  // Returns {ok, discount, message}. Prices are whole dollars.
  function applyCoupon(state, code, price, isNewClient) {
    var c = null, want = String(code || "").trim().toUpperCase();
    if (!want) return { ok: false, discount: 0, message: "" };
    state.coupons.forEach(function (x) { if (x.code === want) c = x; });
    if (!c || !c.active) return { ok: false, discount: 0, message: "That code isn't valid." };
    if (c.expires && iso(new Date()) > c.expires) return { ok: false, discount: 0, message: "That code has expired." };
    if (c.maxUses && c.uses >= c.maxUses) return { ok: false, discount: 0, message: "That code has been used up." };
    if (c.newOnly && !isNewClient) return { ok: false, discount: 0, message: "That code is for new clients only." };
    if (price == null) return { ok: true, discount: 0, message: "Code saved. It applies when your price is set at consultation." };
    var off = c.type === "percent" ? Math.round(price * c.value / 100) : Math.min(price, c.value);
    return { ok: true, discount: off, message: "Code applied: $" + off + " off." };
  }

  window.GG = {
    SERVICES: SERVICES, HOURS: HOURS, DEPOSIT: DEPOSIT, AFTER_HOURS_FEE: AFTER_HOURS_FEE, AFTER_HOURS_FROM: AFTER_HOURS_FROM,
    load: load, save: save, reset: reset, newId: newId, iso: iso, addDays: addDays, weekday: weekday,
    toMin: toMin, fromMin: fromMin, label: label, service: service,
    availableSlots: availableSlots, isAfterHours: isAfterHours,
    findClient: findClient, isBanned: isBanned, consentCurrent: consentCurrent, applyCoupon: applyCoupon
  };
})();
