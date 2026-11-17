/* Gabbs Glamour demo: Gabby's admin dashboard.
 *
 * Reads and writes the shared demo store (window.GG, data.js), so every
 * change here shows up on the booking page in the same browser.
 * Nothing is sent anywhere.
 */
(function () {
  "use strict";

  var state = GG.load();
  var weekOffset = 0;

  var DEPOSIT_LABEL = {
    apple_pay: "Apple Pay", cash_app: "Cash App Pay", google_pay: "Google Pay",
    card: "Card", zelle: "Zelle", cash: "Cash", none: "No deposit"
  };
  var DOW = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var MONTH = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

  /* ---------- small helpers ---------- */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function parse(isoStr) { var p = isoStr.split("-"); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function today() { return GG.iso(new Date()); }
  function shift(date, n) { var d = new Date(date.getTime()); d.setDate(d.getDate() + n); return d; }
  function fmtDay(isoStr) { var d = parse(isoStr); return DOW[d.getDay()].slice(0, 3) + ", " + MON[d.getMonth()] + " " + d.getDate(); }
  function fmtLong(isoStr) { var d = parse(isoStr); return DOW[d.getDay()] + ", " + MONTH[d.getMonth()] + " " + d.getDate(); }
  function fmtDate(isoStr) { var d = parse(isoStr); return MON[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear(); }
  function fmtPhone(p) {
    var d = String(p || "").replace(/\D/g, "");
    return d.length === 10 ? "(" + d.slice(0, 3) + ") " + d.slice(3, 6) + "-" + d.slice(6) : (p || "");
  }
  function money(n) { return "$" + Number(n || 0).toLocaleString("en-US"); }
  function client(id) { return state.clients.find(function (c) { return c.id === id; }) || null; }
  function firstName(c) { return c ? String(c.name).split(" ")[0] : "there"; }
  function isActive(b) { return b.status !== "canceled" && b.status !== "no_show"; }
  function endTime(b) { var s = GG.service(b.serviceId); return GG.fromMin(GG.toMin(b.start) + (s ? s.minutes : 60)); }
  function byWhen(a, b) { return (a.date + a.start).localeCompare(b.date + b.start); }
  function mondayOf(offset) {
    var d = new Date(); d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7) + offset * 7);
    return d;
  }
  function timeOptions(from, to, selected) {
    var out = "";
    for (var m = GG.toMin(from); m <= GG.toMin(to); m += 30) {
      var t = GG.fromMin(m);
      out += '<option value="' + t + '"' + (t === selected ? " selected" : "") + ">" + GG.label(t) + "</option>";
    }
    return out;
  }
  function nextOpenDate() {
    for (var i = 0; i < 14; i++) { var d = shift(new Date(), i); if (GG.HOURS[d.getDay()]) return GG.iso(d); }
    return today();
  }

  function persist(msg) {
    GG.save(state);
    renderAll();
    if (msg) toast(msg);
  }

  /* ---------- toast ---------- */
  var toastTimer = null;
  function toast(msg) {
    var el = $("#toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove("show"); }, 3400);
  }

  /* ---------- dialog ---------- */
  var dlg = $("#dlg"), dlgBody = $("#dlg-body"), dlgReturn = null, dlgSubmit = null, dlgResolve = null;
  function openDialog(html, onSubmit, onOpen) {
    dlgReturn = document.activeElement;
    dlgBody.innerHTML = html;
    dlgSubmit = onSubmit || null;
    if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
    if (onOpen) onOpen(dlgBody);
    var first = dlgBody.querySelector("[autofocus]") || dlgBody.querySelector("input, select, textarea, button");
    if (first) first.focus();
  }
  function closeDialog() {
    if (dlg.open) { if (typeof dlg.close === "function") dlg.close(); else dlg.removeAttribute("open"); }
  }
  dlg.addEventListener("close", function () {
    if (dlgResolve) { var r = dlgResolve; dlgResolve = null; r(null); }
    dlgSubmit = null;
    if (dlgReturn && document.body.contains(dlgReturn)) dlgReturn.focus();
  });
  dlg.addEventListener("submit", function (e) {
    e.preventDefault();
    if (!dlgSubmit) return closeDialog();
    var keepOpen = dlgSubmit(e.target) === false;
    if (!keepOpen) closeDialog();
  });

  // Confirm with an optional note. Resolves {note} or null.
  function ask(opts) {
    return new Promise(function (resolve) {
      var html = '<form><h2 id="dlg-title">' + esc(opts.title) + "</h2>" +
        '<p class="soft">' + opts.body + "</p>" +
        (opts.note ? '<div class="field"><label for="ask-note">' + esc(opts.note) + '</label><textarea id="ask-note" name="note" maxlength="200" placeholder="' + esc(opts.notePlaceholder || "") + '"></textarea></div>' : "") +
        '<div class="dlg-foot"><button type="button" class="btn ghost quiet" data-action="dlg-close">' + esc(opts.cancel || "Keep it") + "</button>" +
        '<button type="submit" class="btn' + (opts.danger ? " ghost warn" : "") + '">' + esc(opts.confirm) + "</button></div></form>";
      openDialog(html, function (form) {
        var note = form.note ? form.note.value.trim() : "";
        dlgResolve = null;
        resolve({ note: note });
      });
      dlgResolve = resolve;
    });
  }

  /* ---------- tabs ---------- */
  var TABS = ["schedule", "blocks", "clients", "coupons", "settings"];
  function showTab(name, focusTab) {
    if (TABS.indexOf(name) < 0) name = "schedule";
    TABS.forEach(function (t) {
      var tab = $("#tab-" + t), panel = $("#panel-" + t), on = t === name;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
      panel.hidden = !on;
    });
    if (focusTab) $("#tab-" + name).focus();
    try { history.replaceState(null, "", "#" + name); } catch (e) { /* file:// in some browsers */ }
  }
  $all(".tab").forEach(function (tab) {
    tab.addEventListener("click", function () { showTab(tab.dataset.tab); window.scrollTo(0, 0); });
    tab.addEventListener("keydown", function (e) {
      var i = TABS.indexOf(tab.dataset.tab), n = null;
      if (e.key === "ArrowRight") n = (i + 1) % TABS.length;
      if (e.key === "ArrowLeft") n = (i - 1 + TABS.length) % TABS.length;
      if (e.key === "Home") n = 0;
      if (e.key === "End") n = TABS.length - 1;
      if (n !== null) { e.preventDefault(); showTab(TABS[n], true); }
    });
  });

  /* ======================================================
     1. Schedule
     ====================================================== */
  function depositChip(b) {
    var how = DEPOSIT_LABEL[b.deposit] || "Deposit";
    if (b.deposit === "none") return '<span class="chip">No deposit</span>';
    if (b.depositPaid) return '<span class="chip ok">Paid via ' + esc(how) + "</span>";
    if (b.deposit === "zelle") return '<span class="chip warn">Zelle pending</span>';
    return '<span class="chip warn">Deposit due · ' + esc(how) + "</span>";
  }
  function statusChip(b) {
    if (b.status === "canceled") return '<span class="chip">Canceled</span>';
    if (b.status === "no_show") return '<span class="chip warn">No-show</span>';
    return "";
  }

  function renderStats() {
    var mon = GG.iso(mondayOf(0)), sun = GG.iso(shift(mondayOf(0), 6)), t = today();
    var month = t.slice(0, 7);
    var week = state.bookings.filter(function (b) { return b.status !== "canceled" && b.date >= mon && b.date <= sun; }).length;
    var pending = state.bookings.filter(function (b) { return isActive(b) && !b.depositPaid && b.deposit !== "none" && b.date >= t; }).length;
    var noShows = state.bookings.filter(function (b) { return b.status === "no_show" && b.date.slice(0, 7) === month; }).length;
    $("#stats").innerHTML =
      '<div class="stat"><b>' + week + "</b><span>Bookings this week</span></div>" +
      '<div class="stat' + (pending ? " warn" : "") + '"><b>' + pending + "</b><span>Deposits pending</span></div>" +
      '<div class="stat' + (noShows ? " warn" : "") + '"><b>' + noShows + "</b><span>No-shows in " + MONTH[new Date().getMonth()] + "</span></div>";
  }

  function bookingCard(b) {
    var s = GG.service(b.serviceId), c = client(b.clientId), active = isActive(b);
    var name = c ? esc(c.name) : "Unknown client";
    var tags = [depositChip(b), statusChip(b)];
    if (c && c.banned) tags.push('<span class="chip ban">Banned</span>');
    if (c && c.noShows >= 2) tags.push('<span class="chip warn">' + c.noShows + " no-shows</span>");
    if (GG.isAfterHours(b.start)) tags.push('<span class="chip">After hours +' + money(GG.AFTER_HOURS_FEE) + "</span>");
    if (b.coupon) tags.push('<span class="chip pink">' + esc(b.coupon) + "</span>");
    var actions = "";
    if (active) {
      if (!b.depositPaid && b.deposit !== "none") actions += '<button class="btn small" type="button" data-action="paid" data-id="' + b.id + '">Mark deposit received</button>';
      actions += '<button class="btn ghost small" type="button" data-action="sms" data-id="' + b.id + '">Text reminder preview</button>' +
        '<button class="btn ghost small" type="button" data-action="reschedule" data-id="' + b.id + '">Reschedule</button>' +
        '<button class="btn ghost small warn" type="button" data-action="noshow" data-id="' + b.id + '">Mark no-show</button>' +
        '<button class="btn ghost small quiet" type="button" data-action="cancel" data-id="' + b.id + '">Cancel</button>';
    }
    return '<article class="card bk' + (active ? "" : " inactive") + '" aria-label="' + esc((s ? s.name : "Booking") + " at " + GG.label(b.start) + " with " + (c ? c.name : "client")) + '">' +
      '<div class="bk-top"><div class="bk-time">' + GG.label(b.start) + "<small>until " + GG.label(endTime(b)) + "</small></div>" +
      '<div class="bk-total">' + (b.total == null ? "TBD" : money(b.total)) + "<small>total</small></div></div>" +
      '<div><p class="bk-svc">' + esc(s ? s.name : b.serviceId) + '</p><p class="bk-client">' + name + (c ? ' · <a href="tel:' + esc(c.phone) + '">' + fmtPhone(c.phone) + "</a>" : "") + "</p></div>" +
      '<div class="chips">' + tags.join("") + "</div>" +
      (actions ? '<div class="actions">' + actions + "</div>" : "") +
      "</article>";
  }

  function renderSchedule() {
    renderStats();
    var mon = mondayOf(weekOffset), t = today();
    var sun = shift(mon, 6);
    var label = weekOffset === 0 ? "This week" : weekOffset === 1 ? "Next week" : weekOffset === -1 ? "Last week" : "Week of " + MON[mon.getMonth()] + " " + mon.getDate();
    $("#week-label").textContent = label + " · " + MON[mon.getMonth()] + " " + mon.getDate() + " to " + MON[sun.getMonth()] + " " + sun.getDate();

    var strip = "", agenda = "";
    for (var i = 0; i < 7; i++) {
      var d = shift(mon, i), iso = GG.iso(d), hours = GG.HOURS[d.getDay()];
      var dayB = state.bookings.filter(function (b) { return b.date === iso; }).sort(byWhen);
      var live = dayB.filter(isActive);
      var blockedDay = state.blocks.some(function (k) { return k.type === "day" && k.date === iso; });
      var closed = !hours || blockedDay;
      var cls = "day-tile" + (iso === t ? " today" : "") + (closed && !live.length ? " closed" : "");
      var cnt = live.length ? '<span class="dot" aria-hidden="true"></span>' + live.length + " booked" : closed ? (blockedDay ? "Blocked" : "Closed") : "Open";
      strip += '<button type="button" class="' + cls + '" data-action="jump" data-day="' + iso + '" aria-label="' + esc(fmtLong(iso) + ": " + cnt.replace(/<[^>]+>/g, "")) + '">' +
        '<span class="dow">' + DOW[d.getDay()].slice(0, 3) + '</span><span class="num">' + d.getDate() + '</span><span class="cnt">' + cnt + "</span></button>";

      var head = '<h3>' + (iso === t ? '<span class="chip pink">Today</span>' : "") + "<span>" + esc(fmtLong(iso)) + "</span>" +
        (hours && !blockedDay ? '<span class="hrs">' + GG.label(hours.open) + " to " + GG.label(hours.close) + "</span>" : "") + "</h3>";
      var body;
      if (dayB.length) body = '<div class="agenda-list">' + dayB.map(bookingCard).join("") + "</div>";
      else if (blockedDay) body = '<p class="empty">Blocked off all day. Clients can\'t book.</p>';
      else if (!hours) body = '<p class="empty">Closed.</p>';
      else {
        var n = GG.availableSlots(state, iso, "volume-fill").length;
        body = '<p class="empty">No bookings yet' + (iso >= t ? " · " + n + " openings for a 90-minute refill" : "") + ".</p>";
      }
      agenda += '<section class="agenda-day' + (closed && !dayB.length ? " closed" : "") + '" id="day-' + iso + '" tabindex="-1">' + head + body + "</section>";
    }
    $("#week-strip").innerHTML = strip;
    $("#agenda").innerHTML = agenda;
  }

  function bookingById(id) { return state.bookings.find(function (b) { return b.id === id; }); }

  function markPaid(b) {
    b.depositPaid = true;
    persist("Deposit marked received for " + (client(b.clientId) || {}).name + ".");
  }

  function markNoShow(b) {
    var c = client(b.clientId), s = GG.service(b.serviceId);
    var next = c ? c.noShows + 1 : 0;
    ask({
      title: "Mark as a no-show?",
      body: esc(c ? c.name : "This client") + " missed the " + esc(s ? s.name : "appointment") + " on " + esc(fmtDay(b.date)) + " at " + GG.label(b.start) +
        ". Their no-show count goes to <b>" + next + "</b>." + (b.depositPaid ? " The deposit stays with you." : "") +
        (next >= 2 ? " At 2 or more, consider banning them from online booking on the Clients tab." : ""),
      confirm: "Mark no-show", danger: true
    }).then(function (r) {
      if (!r) return;
      b.status = "no_show";
      if (c) c.noShows = next;
      persist("Marked no-show. " + (c ? c.name + " now has " + next + " no-show" + (next === 1 ? "" : "s") + "." : ""));
    });
  }

  function cancelBooking(b) {
    var c = client(b.clientId), s = GG.service(b.serviceId);
    ask({
      title: "Cancel this booking?",
      body: esc(s ? s.name : "Appointment") + " with " + esc(c ? c.name : "client") + " on " + esc(fmtDay(b.date)) + " at " + GG.label(b.start) +
        ". The time opens back up on the booking page." + (b.depositPaid ? " Refund the deposit in Square or Zelle yourself if you're returning it." : ""),
      confirm: "Cancel booking", cancel: "Keep booking", danger: true
    }).then(function (r) {
      if (!r) return;
      b.status = "canceled";
      persist("Booking canceled. That time is open again.");
    });
  }

  function smsText(b) {
    var c = client(b.clientId), s = GG.service(b.serviceId);
    var dep = b.depositPaid ? "Your " + money(GG.DEPOSIT) + " deposit is received and goes toward your total." :
      b.deposit === "zelle" ? "Reminder: your " + money(GG.DEPOSIT) + " deposit by Zelle to Gabssglamourllc@gmail.com is still pending." : "";
    return "Hi " + firstName(c) + ", it's Gabbs Glamour. Reminder: your " + (s ? s.name : "appointment") + " is tomorrow, " + fmtDay(b.date) + " at " + GG.label(b.start) + ".\n\n" +
      (dep ? dep + "\n\n" : "") +
      "Please come with clean lashes, no mascara. Need to change your time? Reply to this text.";
  }
  function smsPreview(b) {
    var c = client(b.clientId);
    openDialog('<h2 id="dlg-title">Text reminder preview</h2>' +
      '<p class="soft">Sent automatically 24 hours before, by text and email. This is what ' + esc(c ? c.name : "the client") + " would get" + (c ? " at " + fmtPhone(c.phone) : "") + ".</p>" +
      '<div class="phone" aria-label="Sample text message"><div class="from">Gabbs Glamour</div><div class="bubble">' + esc(smsText(b)) + '</div><div class="meta">Text message · Demo only, nothing is sent</div></div>' +
      '<div class="dlg-foot"><button type="button" class="btn" data-action="dlg-close">Done</button></div>');
  }

  function slotOptions(st, date, serviceId, keep) {
    var slots = GG.availableSlots(st, date, serviceId);
    if (date === today()) {
      // Today: only start times still ahead of now.
      var now = new Date(), nowMin = now.getHours() * 60 + now.getMinutes();
      slots = slots.filter(function (t) { return GG.toMin(t) > nowMin; });
    }
    if (!slots.length) return { html: '<option value="">No openings that day</option>', count: 0 };
    return {
      html: slots.map(function (t) {
        return '<option value="' + t + '"' + (t === keep ? " selected" : "") + ">" + GG.label(t) + (GG.isAfterHours(t) ? " (after hours)" : "") + "</option>";
      }).join(""),
      count: slots.length
    };
  }

  function reschedule(b) {
    var c = client(b.clientId), s = GG.service(b.serviceId);
    var others = Object.assign({}, state, { bookings: state.bookings.filter(function (x) { return x.id !== b.id; }) });
    var html = '<form novalidate><h2 id="dlg-title">Reschedule</h2>' +
      '<p class="soft">' + esc(s ? s.name : "") + " with " + esc(c ? c.name : "client") + ", now " + esc(fmtDay(b.date)) + " at " + GG.label(b.start) + ". Only real openings are offered.</p>" +
      '<div class="field-row"><div class="field"><label for="rs-date">New date</label><input type="date" id="rs-date" name="date" min="' + today() + '" value="' + (b.date >= today() ? b.date : nextOpenDate()) + '" required></div>' +
      '<div class="field"><label for="rs-time">New time</label><select id="rs-time" name="time" aria-describedby="rs-hint"></select></div></div>' +
      '<p class="hint" id="rs-hint" aria-live="polite"></p>' +
      '<div class="dlg-foot"><button type="button" class="btn ghost quiet" data-action="dlg-close">Never mind</button><button type="submit" class="btn">Move booking</button></div></form>';
    function refresh(root) {
      var date = $("#rs-date", root).value;
      var o = slotOptions(others, date, b.serviceId, date === b.date ? b.start : null);
      $("#rs-time", root).innerHTML = o.html;
      $("#rs-hint", root).textContent = !date ? "Pick a date." : !GG.HOURS[GG.weekday(date)] ? "You're closed that day." : o.count + " opening" + (o.count === 1 ? "" : "s") + " on " + fmtDay(date) + ".";
    }
    openDialog(html, function (form) {
      var date = form.date.value, time = form.time.value;
      if (!date || !time) { $("#rs-hint").textContent = "Pick a date with an opening."; return false; }
      var fee = GG.AFTER_HOURS_FEE;
      if (b.total != null) b.total = b.total - (GG.isAfterHours(b.start) ? fee : 0) + (GG.isAfterHours(time) ? fee : 0);
      b.date = date; b.start = time;
      persist("Moved to " + fmtDay(date) + " at " + GG.label(time) + ".");
    }, function (root) {
      refresh(root);
      $("#rs-date", root).addEventListener("change", function () { refresh(root); });
    });
  }

  function addBooking() {
    var clientOpts = state.clients.slice().sort(function (a, b) { return a.name.localeCompare(b.name); }).map(function (c) {
      return '<option value="' + c.id + '">' + esc(c.name) + (c.banned ? " (banned)" : "") + "</option>";
    }).join("");
    var svcOpts = GG.SERVICES.map(function (s) {
      return '<option value="' + s.id + '"' + (s.id === "volume-fill" ? " selected" : "") + ">" + esc(s.name) + (s.price != null ? " · " + money(s.price) : " · price at consult") + "</option>";
    }).join("");
    var depOpts = ["cash_app", "apple_pay", "google_pay", "card", "zelle", "cash", "none"].map(function (k) {
      return '<option value="' + k + '"' + (k === "zelle" ? " selected" : "") + ">" + DEPOSIT_LABEL[k] + "</option>";
    }).join("");
    var html = '<form novalidate><h2 id="dlg-title">Add a booking</h2>' +
      '<p class="soft">For phone calls, DMs and walk-ins. The time comes off the booking page right away.</p>' +
      '<div class="field"><label for="ab-client">Client</label><select id="ab-client" name="client"><option value="__new">New client</option>' + clientOpts + "</select>" +
      '<p class="err" id="ab-client-warn"></p></div>' +
      '<div id="ab-new"><div class="field"><label for="ab-name">Name</label><input id="ab-name" name="name" autocomplete="off" aria-describedby="ab-name-err"><p class="err" id="ab-name-err" role="alert"></p></div>' +
      '<div class="field-row"><div class="field"><label for="ab-phone">Phone</label><input id="ab-phone" name="phone" type="tel" inputmode="tel" autocomplete="off" aria-describedby="ab-phone-err"><p class="err" id="ab-phone-err" role="alert"></p></div>' +
      '<div class="field"><label for="ab-email">Email <span class="muted">(optional)</span></label><input id="ab-email" name="email" type="email" autocomplete="off"></div></div></div>' +
      '<div class="field"><label for="ab-svc">Service</label><select id="ab-svc" name="service">' + svcOpts + "</select></div>" +
      '<div class="field" id="ab-price-wrap" hidden><label for="ab-price">Price set at consult ($)</label><input id="ab-price" name="price" type="number" min="0" step="1" inputmode="numeric" placeholder="Leave blank if not set yet"></div>' +
      '<div class="field-row"><div class="field"><label for="ab-date">Date</label><input type="date" id="ab-date" name="date" min="' + today() + '" value="' + nextOpenDate() + '"></div>' +
      '<div class="field"><label for="ab-time">Time</label><select id="ab-time" name="time" aria-describedby="ab-time-hint"></select></div></div>' +
      '<p class="hint" id="ab-time-hint" aria-live="polite" style="margin-top:-6px;margin-bottom:12px"></p>' +
      '<div class="field-row"><div class="field"><label for="ab-dep">Deposit</label><select id="ab-dep" name="deposit">' + depOpts + "</select></div>" +
      '<div class="field"><label for="ab-coupon">Coupon <span class="muted">(optional)</span></label><input id="ab-coupon" name="coupon" autocomplete="off" autocapitalize="characters" spellcheck="false"></div></div>' +
      '<div class="field"><label class="check"><input type="checkbox" name="paid" id="ab-paid"> Deposit already received</label></div>' +
      '<div class="sum" id="ab-sum" aria-live="polite"></div>' +
      '<div class="dlg-foot"><button type="button" class="btn ghost quiet" data-action="dlg-close">Cancel</button><button type="submit" class="btn">Add booking</button></div></form>';

    function calc(root) {
      var f = $("form", root), svc = GG.service(f.service.value), time = f.time.value;
      var isNew = f.client.value === "__new" || !state.bookings.some(function (b) { return b.clientId === f.client.value && b.status !== "canceled"; });
      var price = svc.price != null ? svc.price : (f.price.value === "" ? null : Math.max(0, Math.round(+f.price.value)));
      var fee = time && GG.isAfterHours(time) ? GG.AFTER_HOURS_FEE : 0;
      var cp = GG.applyCoupon(state, f.coupon.value, price, isNew);
      var total = price == null ? null : price + fee - (cp.ok ? cp.discount : 0);
      return { svc: svc, price: price, fee: fee, cp: cp, total: total, time: time };
    }
    function refresh(root, slotsToo) {
      var f = $("form", root);
      $("#ab-new", root).hidden = f.client.value !== "__new";
      var c = client(f.client.value);
      $("#ab-client-warn", root).textContent = c && c.banned ? "This client is banned from online booking. You can still book them yourself." : "";
      $("#ab-price-wrap", root).hidden = GG.service(f.service.value).price != null;
      if (slotsToo) {
        var keep = f.time.value, date = f.date.value;
        var o = slotOptions(state, date, f.service.value, keep);
        f.time.innerHTML = o.html;
        $("#ab-time-hint", root).textContent = !date ? "Pick a date." : !GG.HOURS[GG.weekday(date)] ? "You're closed that day." : o.count + " opening" + (o.count === 1 ? "" : "s") + " for this service on " + fmtDay(date) + ".";
      }
      var r = calc(root);
      $("#ab-sum", root).innerHTML =
        "<div><span>" + esc(r.svc.name) + "</span><span>" + (r.price == null ? "At consult" : money(r.price)) + "</span></div>" +
        (r.fee ? "<div><span>After-hours fee</span><span>" + money(r.fee) + "</span></div>" : "") +
        (f.coupon.value.trim() ? "<div><span>" + esc(f.coupon.value.trim().toUpperCase()) + "</span><span>" + (r.cp.ok ? (r.cp.discount ? "-" + money(r.cp.discount) : "Saved") : esc(r.cp.message)) + "</span></div>" : "") +
        '<div class="tot"><span>Total</span><span>' + (r.total == null ? "Set at consult" : money(r.total)) + "</span></div>";
    }

    openDialog(html, function (form) {
      var root = dlgBody, ok = true, clientId = form.client.value;
      ["#ab-name-err", "#ab-phone-err"].forEach(function (s) { $(s, root).textContent = ""; });
      [form.name, form.phone].forEach(function (i) { i.removeAttribute("aria-invalid"); });
      var phone = form.phone.value.replace(/\D/g, "");
      if (phone.length === 11 && phone[0] === "1") phone = phone.slice(1);
      if (clientId === "__new") {
        if (!form.name.value.trim()) { $("#ab-name-err", root).textContent = "Add the client's name."; form.name.setAttribute("aria-invalid", "true"); ok = false; }
        if (phone.length !== 10) { $("#ab-phone-err", root).textContent = "Enter a 10-digit phone number."; form.phone.setAttribute("aria-invalid", "true"); ok = false; }
        var existing = ok ? GG.findClient(state, phone, form.email.value) : null;
        if (existing) { $("#ab-phone-err", root).textContent = "That's " + existing.name + ". Pick them from the client list."; form.phone.setAttribute("aria-invalid", "true"); ok = false; }
      }
      if (!form.time.value) { $("#ab-time-hint", root).textContent = "Pick a date with an opening."; ok = false; }
      if (!ok) { var bad = root.querySelector('[aria-invalid="true"]') || form.date; bad.focus(); return false; }
      if (clientId === "__new") {
        var nc = { id: GG.newId(state, "c"), name: form.name.value.trim(), phone: phone, email: form.email.value.trim(), consentSignedAt: null, noShows: 0, banned: false, note: "Added by Gabby (phone or walk-in)." };
        state.clients.push(nc);
        clientId = nc.id;
      }
      var r = calc(root);
      var code = r.cp.ok ? form.coupon.value.trim().toUpperCase() : null;
      if (code) state.coupons.forEach(function (c) { if (c.code === code) c.uses = (c.uses || 0) + 1; });
      state.bookings.push({
        id: GG.newId(state, "b"), clientId: clientId, serviceId: form.service.value, date: form.date.value, start: form.time.value,
        status: "confirmed", deposit: form.deposit.value, depositPaid: form.deposit.value !== "none" && form.paid.checked, coupon: code, total: r.total
      });
      // Jump the schedule to the week the new booking lands in.
      weekOffset = Math.floor(Math.round((parse(form.date.value) - mondayOf(0)) / 864e5) / 7);
      persist("Booked " + r.svc.name + " on " + fmtDay(form.date.value) + " at " + GG.label(form.time.value) + ".");
    }, function (root) {
      refresh(root, true);
      var f = $("form", root);
      ["client", "coupon", "price"].forEach(function (n) { f[n].addEventListener("input", function () { refresh(root, false); }); });
      f.client.addEventListener("change", function () { refresh(root, false); });
      f.time.addEventListener("change", function () { refresh(root, false); });
      f.service.addEventListener("change", function () { refresh(root, true); });
      f.date.addEventListener("change", function () { refresh(root, true); });
    });
  }

  /* ======================================================
     2. Block off time
     ====================================================== */
  var bf = $("#block-form");
  function initBlockForm() {
    $("#bf-weekday").innerHTML = [2, 3, 4, 5, 6, 0, 1].map(function (d) {
      return '<option value="' + d + '">Every ' + DOW[d] + (GG.HOURS[d] ? "" : " (already closed)") + "</option>";
    }).join("");
    $("#bf-start").innerHTML = timeOptions("07:00", "21:30", "12:00");
    $("#bf-end").innerHTML = timeOptions("07:30", "22:00", "14:00");
    $("#bf-date").min = today();
    $("#bf-date").value = nextOpenDate();
    $("#bf-weekday").value = String(parse(nextOpenDate()).getDay());
    bf.addEventListener("change", updateBlockForm);
    bf.addEventListener("input", updateBlockForm);
    bf.addEventListener("submit", function (e) { e.preventDefault(); submitBlock(); });
    updateBlockForm();
  }
  function blockType() { return bf.btype.value; }
  function candidateBlock() {
    var type = blockType(), k = { type: type, reason: bf.reason.value.trim() };
    if (type === "day") k.date = bf.date.value;
    if (type === "range") { k.date = bf.date.value; k.start = bf.start.value; k.end = bf.end.value; }
    if (type === "weekly") { k.weekday = Number(bf.weekday.value); k.start = bf.start.value; k.end = bf.end.value; }
    return k;
  }
  function blockProblems(k) {
    var p = {};
    if (k.type !== "weekly") {
      if (!k.date) p.date = "Pick a date.";
      else if (k.date < today()) p.date = "That date has passed.";
    }
    if (k.type !== "day" && GG.toMin(k.end) <= GG.toMin(k.start)) p.time = "The end time needs to be after the start time.";
    return p;
  }
  function sampleDate(k) {
    if (k.type !== "weekly") return k.date;
    for (var i = 0; i < 7; i++) { var d = shift(new Date(), i); if (d.getDay() === k.weekday) return GG.iso(d); }
    return today();
  }
  function updateBlockForm() {
    var type = blockType();
    $("#bf-date-wrap").hidden = type === "weekly";
    $("#bf-weekday-wrap").hidden = type !== "weekly";
    $("#bf-times").hidden = type === "day";
    var k = candidateBlock(), p = blockProblems(k);
    $("#bf-date-err").textContent = p.date || "";
    $("#bf-time-err").textContent = p.time || "";
    $("#bf-date").setAttribute("aria-invalid", p.date ? "true" : "false");
    $("#bf-end").setAttribute("aria-invalid", p.time ? "true" : "false");
    var pv = $("#bf-preview");
    if (p.date || p.time) { pv.innerHTML = '<p class="muted">Fix the highlighted field to see the effect.</p>'; return; }
    var date = sampleDate(k), svcId = "volume-fill", svc = GG.service(svcId);
    if (!GG.HOURS[GG.weekday(date)]) {
      pv.innerHTML = '<p class="big">No change for clients</p><p class="muted">You\'re already closed on ' + DOW[GG.weekday(date)] + "s, so the booking page shows nothing then anyway.</p>";
      return;
    }
    var before = GG.availableSlots(state, date, svcId);
    var after = GG.availableSlots(Object.assign({}, state, { blocks: state.blocks.concat([k]) }), date, svcId);
    var lost = before.length - after.length;
    var booked = state.bookings.filter(function (b) {
      if (b.date !== date || !isActive(b)) return false;
      if (k.type === "day") return true;
      var s = GG.toMin(b.start), e = GG.toMin(endTime(b));
      return s < GG.toMin(k.end) && e > GG.toMin(k.start);
    }).length;
    var when = k.type === "weekly" ? "On " + fmtDay(date) + " (and every " + DOW[k.weekday] + ")" : "On " + fmtDay(date);
    pv.innerHTML = '<p class="big">Clients will see ' + lost + " fewer opening" + (lost === 1 ? "" : "s") + "</p>" +
      '<p class="muted" style="font-size:14px">' + esc(when) + ", for a " + esc(svc.name) + " (" + svc.minutes + " min): " + after.length + " of " + before.length + " start times left.</p>" +
      (before.length ? '<div class="slot-chips" aria-label="Start times after this block">' + before.map(function (t) {
        var gone = after.indexOf(t) < 0;
        return '<span class="chip' + (gone ? " gone" : " ok") + '">' + GG.label(t) + (gone ? '<span class="sr-only"> (removed)</span>' : "") + "</span>";
      }).join("") + "</div>" : "") +
      (booked ? '<p class="err" style="margin-top:10px">You have ' + booked + " booking" + (booked === 1 ? "" : "s") + " in that time. Blocking doesn't cancel " + (booked === 1 ? "it" : "them") + ".</p>" : "");
  }
  function submitBlock() {
    var k = candidateBlock(), p = blockProblems(k);
    if (p.date) { $("#bf-date").focus(); return; }
    if (p.time) { $("#bf-end").focus(); return; }
    k.id = GG.newId(state, "k");
    if (!k.reason) k.reason = "Blocked";
    state.blocks.push(k);
    bf.reason.value = "";
    persist("Blocked: " + describeBlock(k) + ". The booking page is updated.");
  }
  function describeBlock(k) {
    if (k.type === "day") return "All day " + fmtDay(k.date);
    if (k.type === "range") return fmtDay(k.date) + ", " + GG.label(k.start) + " to " + GG.label(k.end);
    return "Every " + DOW[k.weekday] + ", " + GG.label(k.start) + " to " + GG.label(k.end);
  }
  function renderBlocks() {
    var t = today();
    var list = state.blocks.slice().sort(function (a, b) {
      var ka = a.type === "weekly" ? "0" + a.weekday : "1" + a.date + (a.start || "");
      var kb = b.type === "weekly" ? "0" + b.weekday : "1" + b.date + (b.start || "");
      return ka.localeCompare(kb);
    });
    $("#block-list").innerHTML = list.length ? list.map(function (k) {
      var past = k.type !== "weekly" && k.date < t;
      var tag = k.type === "weekly" ? '<span class="chip pink">Weekly</span>' : k.type === "day" ? '<span class="chip">Whole day</span>' : '<span class="chip">Hours</span>';
      return '<div class="card row-item"><div><p class="what">' + esc(describeBlock(k)) + '</p><p class="muted" style="font-size:14px">' + esc(k.reason || "") + "</p>" +
        '<div class="chips" style="margin-top:6px">' + tag + (past ? '<span class="chip">Past</span>' : "") + "</div></div>" +
        '<button class="btn ghost small quiet" type="button" data-action="unblock" data-id="' + k.id + '" aria-label="Remove block: ' + esc(describeBlock(k)) + '">Remove</button></div>';
    }).join("") : '<p class="empty">Nothing blocked. Every open hour is bookable.</p>';
    updateBlockForm();
  }

  /* ======================================================
     3. Clients
     ====================================================== */
  function consentChip(c) {
    if (!c.consentSignedAt) return '<span class="chip warn">Consent missing</span>';
    if (GG.consentCurrent(c)) return '<span class="chip ok">Consent signed ' + esc(fmtDate(c.consentSignedAt)) + "</span>";
    return '<span class="chip warn">Consent expired, needs re-sign</span>';
  }
  function renderClients() {
    var q = $("#client-search").value.trim().toLowerCase(), qd = q.replace(/\D/g, "");
    var all = state.clients.slice().sort(function (a, b) { return a.name.localeCompare(b.name); });
    var shown = all.filter(function (c) {
      if (!q) return true;
      return c.name.toLowerCase().indexOf(q) >= 0 || (c.email || "").toLowerCase().indexOf(q) >= 0 || (qd && c.phone.indexOf(qd) >= 0);
    });
    var banned = all.filter(function (c) { return c.banned; }).length;
    $("#client-count").textContent = all.length + " client" + (all.length === 1 ? "" : "s") + (banned ? ", " + banned + " banned from online booking" : "") + ".";
    var t = today();
    $("#client-list").innerHTML = shown.length ? shown.map(function (c) {
      var visits = state.bookings.filter(function (b) { return b.clientId === c.id; }).sort(byWhen).reverse();
      var hist = visits.length ? '<ul class="history">' + visits.map(function (b) {
        var s = GG.service(b.serviceId);
        var st = b.status === "canceled" ? '<span class="chip">Canceled</span>' : b.status === "no_show" ? '<span class="chip warn">No-show</span>' :
          b.date >= t ? '<span class="chip pink">Upcoming</span>' : '<span class="chip ok">Done</span>';
        return "<li><span>" + esc(fmtDate(b.date)) + " · " + esc(s ? s.name : b.serviceId) + "</span>" + st + "</li>";
      }).join("") + "</ul>" : '<p class="muted" style="margin:0;font-size:14px">No visits on the books yet.</p>';
      return '<article class="card client' + (c.banned ? " banned" : "") + '" aria-labelledby="cl-' + c.id + '">' +
        '<div><h3 id="cl-' + c.id + '">' + esc(c.name) + "</h3>" +
        '<p class="client-contact"><a href="tel:' + esc(c.phone) + '">' + esc(fmtPhone(c.phone)) + "</a>" + (c.email ? '<a href="mailto:' + esc(c.email) + '">' + esc(c.email) + "</a>" : "") + "</p></div>" +
        '<div class="chips">' + (c.banned ? '<span class="chip ban">Banned</span>' : "") + consentChip(c) +
        '<span class="chip' + (c.noShows >= 2 ? " warn" : "") + '">' + c.noShows + " no-show" + (c.noShows === 1 ? "" : "s") + "</span></div>" +
        '<div class="field" style="margin:0"><label for="note-' + c.id + '">Private note</label><textarea id="note-' + c.id + '" data-note="' + c.id + '" maxlength="500">' + esc(c.note || "") + "</textarea>" +
        '<div class="actions" style="margin-top:8px"><button class="btn ghost small" type="button" data-action="save-note" data-id="' + c.id + '">Save note</button></div></div>' +
        "<details><summary>Visit history (" + visits.length + ")</summary>" + hist + "</details>" +
        '<div class="actions"><button class="btn ghost small" type="button" data-action="consent" data-id="' + c.id + '">View consent form</button>' +
        (c.banned ? '<button class="btn ghost small" type="button" data-action="unban" data-id="' + c.id + '">Unban</button>' :
          '<button class="btn ghost small warn" type="button" data-action="ban" data-id="' + c.id + '">Ban from online booking</button>') + "</div>" +
        "</article>";
    }).join("") : '<p class="empty">No clients match "' + esc(q) + '".</p>';
  }
  function stampNote(c, what, why) {
    var line = what + " " + fmtDate(today()) + (why ? ": " + why : "");
    c.note = c.note ? c.note + "\n" + line : line;
  }
  function ban(c) {
    var upcoming = state.bookings.filter(function (b) { return b.clientId === c.id && isActive(b) && b.date >= today(); }).length;
    ask({
      title: "Ban " + c.name + "?",
      body: "They'll see \"Online booking isn't available, please contact Gabby\" on the booking page. They aren't told they're banned." +
        (upcoming ? " They still have " + upcoming + " upcoming booking" + (upcoming === 1 ? "" : "s") + ", which stay" + (upcoming === 1 ? "s" : "") + " on your schedule unless you cancel." : ""),
      note: "Why? (saved to their private note)", notePlaceholder: "For example: third no-show",
      confirm: "Ban from online booking", cancel: "Don't ban", danger: true
    }).then(function (r) {
      if (!r) return;
      c.banned = true;
      stampNote(c, "Banned", r.note);
      persist(c.name + " can no longer book online.");
    });
  }
  function unban(c) {
    ask({
      title: "Unban " + c.name + "?",
      body: "They'll be able to book online again right away.",
      note: "Note (optional, saved to their private note)", notePlaceholder: "For example: talked it through, paid in full",
      confirm: "Unban", cancel: "Keep banned"
    }).then(function (r) {
      if (!r) return;
      c.banned = false;
      stampNote(c, "Unbanned", r.note);
      persist(c.name + " can book online again.");
    });
  }
  function consentForm(c) {
    var body;
    if (!c.consentSignedAt) {
      body = '<p class="soft">No consent form on file. ' + esc(firstName(c)) + " will be asked to sign it before their next appointment is confirmed.</p>";
    } else {
      var current = GG.consentCurrent(c);
      body = '<div class="chips"><span class="chip pink">Sample on-file summary</span>' + (current ? '<span class="chip ok">Current</span>' : '<span class="chip warn">Expired, needs re-sign</span>') + "</div>" +
        (current ? "" : '<p class="err">Forms are good for a year. ' + esc(firstName(c)) + " will be asked to re-sign at their next booking.</p>") +
        '<dl class="consent-list">' + [
          ["Allergies (adhesive, latex, tape)", "None reported"],
          ["Eye conditions, infections or recent eye surgery", "None"],
          ["Contact lenses", "Wears them, will remove before the appointment"],
          ["Previous lash extensions", c.noShows || state.bookings.some(function (b) { return b.clientId === c.id; }) ? "Yes, no reactions" : "No, first set"],
          ["Understands possible risks (irritation, redness)", "Yes"],
          ["Aftercare: keep dry 24 hours, no oil-based products", "Read and agreed"],
          ["Photos of lashes for Gabby's portfolio", "OK to post, face cropped"],
          ["Signed", esc(c.name) + ", typed signature, " + esc(fmtDate(c.consentSignedAt))]
        ].map(function (r) { return "<div><dt>" + r[0] + "</dt><dd>" + r[1] + "</dd></div>"; }).join("") + "</dl>" +
        '<p class="hint">Sample answers for a demo client. In the real site this shows what the client actually signed.</p>';
    }
    openDialog('<h2 id="dlg-title">Consent form · ' + esc(c.name) + "</h2>" + body +
      '<div class="dlg-foot"><button type="button" class="btn" data-action="dlg-close">Done</button></div>');
  }

  /* ======================================================
     4. Coupons
     ====================================================== */
  function renderCoupons() {
    var t = today();
    $("#coupon-list").innerHTML = state.coupons.length ? state.coupons.map(function (c, i) {
      var expired = c.expires && c.expires < t;
      var usedUp = c.maxUses && c.uses >= c.maxUses;
      var pct = c.maxUses ? Math.min(100, Math.round((c.uses / c.maxUses) * 100)) : 0;
      var off = c.type === "percent" ? c.value + "% off" : money(c.value) + " off";
      return '<article class="card coupon' + (c.active ? "" : " off-state") + '" aria-label="Coupon ' + esc(c.code) + '">' +
        '<div class="coupon-top"><div><div class="code">' + esc(c.code) + '</div><div class="off">' + off + "</div></div>" +
        '<label class="switch"><input type="checkbox" data-toggle="' + i + '"' + (c.active ? " checked" : "") + "> Active</label></div>" +
        '<div class="chips">' + (c.newOnly ? '<span class="chip pink">New clients only</span>' : '<span class="chip">Everyone</span>') +
        (c.expires ? '<span class="chip' + (expired ? " warn" : "") + '">' + (expired ? "Expired " : "Expires ") + esc(fmtDate(c.expires)) + "</span>" : '<span class="chip">No expiry</span>') +
        (usedUp ? '<span class="chip warn">Used up</span>' : "") + (c.active ? "" : '<span class="chip">Off</span>') + "</div>" +
        '<div><div class="muted" style="font-size:14px;margin-bottom:6px">' + c.uses + " use" + (c.uses === 1 ? "" : "s") + (c.maxUses ? " of " + c.maxUses : ", no limit") + "</div>" +
        (c.maxUses ? '<div class="meter" role="img" aria-label="' + pct + ' percent used"><i style="width:' + pct + '%"></i></div>' : "") + "</div>" +
        '<div class="actions"><button class="btn ghost small" type="button" data-action="copy" data-code="' + esc(c.code) + '">Copy code</button>' +
        (c.active ? '<button class="btn ghost small quiet" type="button" data-action="deactivate" data-code="' + esc(c.code) + '">Deactivate</button>' : "") + "</div>" +
        "</article>";
    }).join("") : '<p class="empty">No coupons yet.</p>';
  }
  var cf = $("#coupon-form");
  function setErr(input, errId, msg) {
    $(errId).textContent = msg || "";
    if (msg) input.setAttribute("aria-invalid", "true"); else input.removeAttribute("aria-invalid");
    return !msg;
  }
  function initCouponForm() {
    $("#cf-expires").min = today();
    cf.code.addEventListener("input", function () {
      var pos = cf.code.selectionStart;
      cf.code.value = cf.code.value.toUpperCase().replace(/[^A-Z0-9]/g, "");
      try { cf.code.setSelectionRange(pos, pos); } catch (e) { /* not all inputs support it */ }
    });
    cf.type.addEventListener("change", function () {
      $("#cf-value-label").textContent = cf.type.value === "percent" ? "Percent (%)" : "Amount ($)";
      cf.value.max = cf.type.value === "percent" ? 100 : 200;
    });
    cf.addEventListener("submit", function (e) {
      e.preventDefault();
      var code = cf.code.value.trim().toUpperCase(), val = Number(cf.value.value), max = cf.maxUses.value, exp = cf.expires.value;
      var ok = true;
      ok = setErr(cf.code, "#cf-code-err",
        !code ? "Give the coupon a code." :
        !/^[A-Z0-9]{3,16}$/.test(code) ? "Use 3 to 16 letters or numbers, no spaces." :
        state.coupons.some(function (c) { return c.code === code; }) ? code + " already exists. Pick another code." : "") && ok;
      ok = setErr(cf.value, "#cf-value-err",
        cf.value.value === "" || !(val >= 1) || Math.round(val) !== val ? "Enter a whole number, 1 or more." :
        cf.type.value === "percent" && val > 100 ? "Percent off can't be over 100." :
        cf.type.value === "amount" && val > 200 ? "That's more than any service costs." : "") && ok;
      ok = setErr(cf.expires, "#cf-expires-err", exp && exp < today() ? "That date has passed." : "") && ok;
      ok = setErr(cf.maxUses, "#cf-max-err", max !== "" && !(Number(max) >= 1 && Math.round(Number(max)) === Number(max)) ? "Leave blank for no limit, or enter 1 or more." : "") && ok;
      if (!ok) { cf.querySelector('[aria-invalid="true"]').focus(); return; }
      state.coupons.unshift({ code: code, type: cf.type.value, value: val, newOnly: cf.newOnly.checked, expires: exp || null, maxUses: max === "" ? null : Number(max), uses: 0, active: true });
      cf.reset();
      $("#cf-value-label").textContent = "Amount ($)";
      persist(code + " is live. Clients can use it on the booking page.");
    });
  }
  function copyCode(code) {
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = code; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      toast(ok ? "Copied " + code + "." : "Couldn't copy. The code is " + code + ".");
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(code).then(function () { toast("Copied " + code + "."); }, fallback);
    } else fallback();
  }

  /* ======================================================
     5. Settings
     ====================================================== */
  function renderSettings() {
    $("#set-deposit").textContent = money(GG.DEPOSIT);
    $("#set-fee").textContent = money(GG.AFTER_HOURS_FEE) + " from " + GG.label(GG.AFTER_HOURS_FROM);
  }

  /* ---------- wiring ---------- */
  function renderAll() {
    renderSchedule();
    renderBlocks();
    renderClients();
    renderCoupons();
    renderSettings();
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-action]");
    if (!btn) return;
    var a = btn.dataset.action, id = btn.dataset.id;
    if (a === "dlg-close") { closeDialog(); return; }
    if (a === "add-booking") return addBooking();
    if (a === "week-prev") { weekOffset--; renderSchedule(); return; }
    if (a === "week-next") { weekOffset++; renderSchedule(); return; }
    if (a === "jump") {
      var sec = document.getElementById("day-" + btn.dataset.day);
      if (sec) { sec.scrollIntoView({ behavior: "smooth", block: "start" }); sec.focus({ preventScroll: true }); }
      return;
    }
    var b = id ? bookingById(id) : null;
    if (a === "paid" && b) return markPaid(b);
    if (a === "noshow" && b) return markNoShow(b);
    if (a === "cancel" && b) return cancelBooking(b);
    if (a === "reschedule" && b) return reschedule(b);
    if (a === "sms" && b) return smsPreview(b);
    if (a === "unblock") {
      var k = state.blocks.find(function (x) { return x.id === id; });
      state.blocks = state.blocks.filter(function (x) { return x.id !== id; });
      persist(k ? "Removed: " + describeBlock(k) + ". That time is bookable again." : "Block removed.");
      var nextBtn = $("#block-list button");
      (nextBtn || $("#bf-reason")).focus();
      return;
    }
    var c = id ? client(id) : null;
    if (a === "save-note" && c) {
      c.note = $("#note-" + c.id).value.trim();
      persist("Note saved for " + c.name + ".");
      return;
    }
    if (a === "ban" && c) return ban(c);
    if (a === "unban" && c) return unban(c);
    if (a === "consent" && c) return consentForm(c);
    if (a === "copy") return copyCode(btn.dataset.code);
    if (a === "deactivate") {
      var cp = state.coupons.find(function (x) { return x.code === btn.dataset.code; });
      if (cp) { cp.active = false; persist(cp.code + " is off. Clients can't use it."); }
      return;
    }
    if (a === "reset") {
      ask({
        title: "Reset the demo?",
        body: "Puts back the sample clients, bookings, blocked time and coupons. Anything you changed here or booked on the booking page in this browser is cleared.",
        confirm: "Reset demo data", cancel: "Keep my changes", danger: true
      }).then(function (r) {
        if (!r) return;
        state = GG.reset();
        weekOffset = 0;
        renderAll();
        toast("Demo data reset.");
      });
    }
  });

  document.addEventListener("change", function (e) {
    var t = e.target;
    if (t.matches && t.matches("[data-toggle]")) {
      var c = state.coupons[Number(t.dataset.toggle)];
      if (!c) return;
      c.active = t.checked;
      persist(c.code + (c.active ? " is on. Clients can use it." : " is off. Clients can't use it."));
    }
  });

  $("#client-search").addEventListener("input", renderClients);

  // A booking made on book.html in another tab shows up here without a reload.
  window.addEventListener("storage", function () {
    if (dlg.open) return;
    state = GG.load();
    renderAll();
  });

  initBlockForm();
  initCouponForm();
  renderAll();
  showTab((location.hash || "").slice(1) || "schedule");
})();
