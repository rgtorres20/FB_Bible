/* Gabbs Glamour demo: the booking flow.
 *
 * Six screens driven by one `draft` object. Nothing leaves the browser: the
 * finished booking is written to the shared demo store (data.js) so the admin
 * page can see it.
 */
(function () {
  "use strict";
  var GG = window.GG;
  var state = GG.load();

  var STEPS = [
    { key: "service", label: "Service" },
    { key: "when", label: "Date & time" },
    { key: "info", label: "Your info" },
    { key: "consent", label: "Consent" },
    { key: "pay", label: "Review & pay" },
    { key: "done", label: "Booked" }
  ];
  var METHODS = [
    { key: "apple_pay", name: "Apple Pay" },
    { key: "cash_app", name: "Cash App Pay" },
    { key: "google_pay", name: "Google Pay" },
    { key: "card", name: "Card" },
    { key: "zelle", name: "Zelle" }
  ];
  var ZELLE_TO = "Gabssglamourllc@gmail.com";
  var DAYS_AHEAD = 21;

  var draft = {
    serviceId: null, date: null, start: null,
    name: "", phone: "", email: "",
    client: null, consentOnFile: false,
    consent: { answers: {}, checks: {}, typedName: "", signed: false, signedNow: false },
    couponCode: "", coupon: null, method: null,
    booking: null
  };
  var step = 0;

  var screen = document.getElementById("screen");
  var stepper = document.getElementById("stepper");
  var live = document.getElementById("live");

  // ---------- helpers ----------
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v == null || v === false) return;
      if (k === "text") n.textContent = v;
      else if (k === "html") n.innerHTML = v;
      else if (k === "class") n.className = v;
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function money(n) { return "$" + n; }
  function dur(min) {
    var h = Math.floor(min / 60), m = min % 60;
    return (h ? h + " hr" : "") + (h && m ? " " : "") + (m ? m + " min" : "");
  }
  function dateOf(isoStr) { var p = isoStr.split("-"); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function shortDate(isoStr) {
    return dateOf(isoStr).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }).replace(/,/g, "");
  }
  function longDate(isoStr) {
    return dateOf(isoStr).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  }
  function svc() { return GG.service(draft.serviceId); }
  function digits(s) { return String(s || "").replace(/\D/g, ""); }
  function announce(msg) { live.textContent = ""; setTimeout(function () { live.textContent = msg; }, 30); }

  function pricing() {
    var s = svc();
    var fee = draft.start && GG.isAfterHours(draft.start) ? GG.AFTER_HOURS_FEE : 0;
    var discount = draft.coupon && draft.coupon.ok ? draft.coupon.discount : 0;
    var total = s.price == null ? null : Math.max(0, s.price + fee - discount);
    var balance = total == null ? null : Math.max(0, total - GG.DEPOSIT);
    return { price: s.price, fee: fee, discount: discount, total: total, balance: balance };
  }

  function needsConsent() { return !draft.consentOnFile; }

  // ---------- stepper ----------
  function drawStepper() {
    stepper.innerHTML = "";
    STEPS.forEach(function (s, i) {
      var skipped = i === 3 && !needsConsent() && step > 2;
      var cls = i === step ? "current" : (skipped ? "skipped" : (i < step ? "done" : ""));
      var status = i === step ? "current step" : (skipped ? "skipped, consent on file" : (i < step ? "done" : "not started"));
      stepper.appendChild(el("li", { class: cls, "aria-current": i === step ? "step" : null }, [
        el("span", { class: "bar", "aria-hidden": "true" }),
        el("span", { class: "lbl" }, [s.label, el("span", { style: "position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)", text: ", " + status })])
      ]));
    });
  }

  function go(n) {
    step = n;
    render();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function next() { go(step === 2 && !needsConsent() ? 4 : step + 1); }
  function back() { go(step === 4 && !needsConsent() ? 2 : step - 1); }

  function shell(title, sub, body, actions) {
    var wrap = el("section", { class: "step", tabindex: "-1", "aria-labelledby": "step-h" }, [
      el("h2", { id: "step-h", class: "step-title", text: title }),
      sub ? el("p", { class: "step-sub muted", text: sub }) : null
    ].concat(body).concat(actions ? [actions] : []));
    return wrap;
  }
  function actionRow(opts) {
    var err = el("p", { class: "err", role: "alert", "aria-live": "assertive", id: "step-err" });
    var row = el("div", { class: "actions" }, [
      opts.back === false ? el("span", { class: "spacer" }) :
        el("button", { type: "button", class: "btn ghost", text: "Back", onclick: back }),
      el("button", { type: "button", class: "btn", id: "next-btn", text: opts.nextText || "Continue", onclick: opts.onNext })
    ]);
    return el("div", null, [err, row]);
  }
  function showErr(msg) { var e = document.getElementById("step-err"); if (e) e.textContent = msg; }

  function render() {
    drawStepper();
    screen.innerHTML = "";
    var view = [renderService, renderWhen, renderInfo, renderConsent, renderPay, renderDone][step]();
    screen.appendChild(view);
    var h = screen.querySelector("#step-h");
    if (h && render.started) { view.focus({ preventScroll: true }); }
    render.started = true;
  }

  // ---------- 1. service ----------
  function renderService() {
    var groups = [["full", "Full sets"], ["refill", "Refills"], ["other", "Other"]];
    var body = [];
    groups.forEach(function (g) {
      var list = GG.SERVICES.filter(function (s) { return s.kind === g[0]; });
      if (!list.length) return;
      var gid = "grp-" + g[0];
      body.push(el("h3", { class: "group-h", id: gid, text: g[1] }));
      var box = el("div", { role: "group", "aria-labelledby": gid });
      list.forEach(function (s) {
        var priced = s.price != null;
        box.appendChild(el("button", {
          type: "button", class: "opt", "aria-pressed": String(draft.serviceId === s.id),
          onclick: function () {
            if (draft.serviceId !== s.id) { draft.date = null; draft.start = null; draft.coupon = null; }
            draft.serviceId = s.id; render();
          }
        }, [
          el("span", null, [el("span", { class: "name", text: s.name }), el("span", { class: "note", text: s.note })]),
          el("span", { class: "meta" }, [
            el("span", { class: "price" + (priced ? "" : " small"), text: priced ? money(s.price) : "Price at consultation" }),
            el("span", { class: "dur", text: dur(s.minutes) })
          ])
        ]));
      });
      body.push(box);
    });
    body.push(el("p", { class: "muted", style: "font-size:14px;margin-top:14px", text: "Refills need at least 50% of your lashes remaining. Otherwise book a full set." }));
    return shell("Choose your service", "A $" + GG.DEPOSIT + " deposit holds your spot and goes toward your total.", body, actionRow({
      back: false,
      onNext: function () { if (!draft.serviceId) return showErr("Pick a service to continue."); next(); }
    }));
  }

  // ---------- 2. date & time ----------
  function renderWhen() {
    var s = svc();
    var days = el("div", { class: "days", role: "group", "aria-label": "Choose a day" });
    var firstOpen = null;
    for (var i = 1; i <= DAYS_AHEAD; i++) {
      (function (d) {
        var dIso = GG.iso(d);
        var open = !!GG.HOURS[d.getDay()];
        if (open && !firstOpen) firstOpen = dIso;
        var label = d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" }) + (open ? "" : ", closed");
        days.appendChild(el("button", {
          type: "button", class: "day", disabled: !open, "aria-label": label,
          "aria-pressed": String(draft.date === dIso),
          onclick: function () { draft.date = dIso; draft.start = null; render(); announce(longDate(dIso) + " selected"); }
        }, [
          el("span", { class: "dow", text: d.toLocaleDateString("en-US", { weekday: "short" }) }),
          el("span", { class: "dnum", text: String(d.getDate()) }),
          el("span", { class: open ? "mon" : "closed", text: open ? d.toLocaleDateString("en-US", { month: "short" }) : "Closed" })
        ]));
      })(GG.addDays(i));
    }
    var body = [el("p", { class: "pill-row" }, [el("span", { class: "chip pink", text: s.name }), el("span", { class: "chip", text: dur(s.minutes) })]), days];

    if (!draft.date) {
      body.push(el("p", { class: "empty", text: "Pick a day to see open times." }));
    } else {
      var slots = GG.availableSlots(state, draft.date, s.id);
      body.push(el("h3", { class: "group-h", id: "slots-h", text: longDate(draft.date) }));
      if (!slots.length) {
        body.push(el("p", { class: "empty", text: "No openings this day" }));
      } else {
        var grid = el("div", { class: "slots", role: "group", "aria-labelledby": "slots-h" });
        slots.forEach(function (t) {
          var late = GG.isAfterHours(t);
          grid.appendChild(el("button", {
            type: "button", class: "slot", "aria-pressed": String(draft.start === t),
            "aria-label": GG.label(t) + (late ? ", plus $" + GG.AFTER_HOURS_FEE + " after-hours fee" : ""),
            onclick: function () { draft.start = t; render(); announce(GG.label(t) + " selected"); var b = document.getElementById("next-btn"); if (b) b.focus(); }
          }, [GG.label(t), late ? el("span", { class: "fee", text: "+$" + GG.AFTER_HOURS_FEE + " after-hours" }) : null]));
        });
        body.push(grid);
        if (slots.some(GG.isAfterHours)) body.push(el("p", { class: "muted", style: "font-size:13px;margin-top:10px", text: "Appointments starting at 5:30 PM or later carry a $" + GG.AFTER_HOURS_FEE + " after-hours fee." }));
      }
    }
    return shell("Pick a day and time", "Showing the next three weeks. Tuesday through Saturday.", body, actionRow({
      onNext: function () {
        if (!draft.date) return showErr("Pick a day first.");
        if (!draft.start) return showErr("Pick a start time.");
        next();
      }
    }));
  }

  // ---------- 3. your info ----------
  function field(id, labelText, input, hint) {
    input.id = id;
    if (hint) input.setAttribute("aria-describedby", id + "-hint");
    return el("div", { class: "field" }, [el("label", { for: id, text: labelText }), input, hint ? el("p", { class: "hint", id: id + "-hint", text: hint }) : null]);
  }
  function renderInfo() {
    var name = el("input", { type: "text", autocomplete: "name", required: true, value: draft.name });
    var phone = el("input", { type: "tel", autocomplete: "tel", inputmode: "tel", required: true, value: draft.phone });
    var email = el("input", { type: "email", autocomplete: "email", required: true, value: draft.email });
    var onFile = el("div", { "aria-live": "polite" });

    function check() {
      draft.name = name.value; draft.phone = phone.value; draft.email = email.value;
      var c = GG.findClient(state, phone.value, email.value);
      onFile.innerHTML = "";
      if (c && !c.banned && GG.consentCurrent(c)) {
        onFile.appendChild(el("p", { class: "chip ok", text: "Consent on file" }));
        onFile.appendChild(el("p", { class: "muted", style: "font-size:14px;margin:6px 0 0", text: "Welcome back. Your signed consent form is current, so you can skip straight to review." }));
      }
    }
    [name, phone, email].forEach(function (i) { i.addEventListener("input", check); });

    var body = [
      field("f-name", "Full name", name),
      field("f-phone", "Mobile phone", phone, "Your confirmation and reminder come by text."),
      field("f-email", "Email", email),
      onFile
    ];
    var view = shell("Your info", "So Gabby knows who is coming and can reach you.", body, actionRow({
      onNext: function () {
        check();
        if (draft.name.trim().length < 2) { name.focus(); return showErr("Enter your full name."); }
        if (digits(draft.phone).length < 10) { phone.focus(); return showErr("Enter a 10-digit mobile number."); }
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(draft.email.trim())) { email.focus(); return showErr("Enter a valid email address."); }
        if (GG.isBanned(state, draft.phone, draft.email)) return renderStop();
        draft.client = GG.findClient(state, draft.phone, draft.email);
        draft.consentOnFile = !!(draft.client && GG.consentCurrent(draft.client));
        if (!draft.consentOnFile && draft.consent.typedName === "") draft.consent.typedName = draft.name.trim();
        next();
      }
    }));
    setTimeout(check, 0);
    return view;
  }
  function renderStop() {
    screen.innerHTML = "";
    var v = el("section", { class: "step card stop-card", tabindex: "-1", "aria-labelledby": "stop-h" }, [
      el("h2", { id: "stop-h", class: "step-title", text: "Sorry, online booking isn't available." }),
      el("p", { class: "soft", text: "Please contact Gabby directly." }),
      el("p", null, [el("a", { class: "btn ghost", href: "./", text: "Back to home" })])
    ]);
    screen.appendChild(v);
    v.focus();
  }

  // ---------- 4. consent ----------
  var QUESTIONS = [
    ["allergy", "Any allergy to lash adhesive, latex, or cyanoacrylate?"],
    ["eye", "Any eye condition (infection, dry eye, glaucoma, blepharitis)?"],
    ["surgery", "Eye surgery (including LASIK) in the last 6 months?"],
    ["pregnant", "Are you pregnant?"],
    ["contacts", "Do you wear contact lenses?"]
  ];
  var ACKS = [
    ["risks", "I understand the risks of lash extensions, including irritation, allergic reaction, and natural lash damage if they are not cared for."],
    ["aftercare", "I will follow aftercare, including keeping my lashes dry for the first 24 hours."],
    ["policies", "I agree to the booking policies: 10-minute grace period, non-refundable deposit, and 24-hour cancellation notice."]
  ];

  function renderConsent() {
    var c = draft.consent;
    var text = el("div", { class: "consent-text", tabindex: "0", role: "region", "aria-label": "Lash extension consent" }, [
      el("p", { text: "Lash extensions are single synthetic fibres bonded to your natural lashes with a cyanoacrylate-based adhesive. Your eyes stay closed for the whole appointment." }),
      el("p", { text: "Possible effects include redness, watering, or irritation during or after the service, and in rare cases an allergic reaction to the adhesive. If you notice swelling, itching, or pain, contact Gabby and see a doctor if it persists." }),
      el("p", { text: "Pulling, rubbing, or picking at extensions can damage your natural lashes. Removal should only be done by a lash professional." }),
      el("p", { text: "Please arrive with clean lashes and no eye makeup. Contact lenses should be removed before your service." })
    ]);

    var qs = el("fieldset", null, [el("legend", { text: "Health questions" })]);
    QUESTIONS.forEach(function (q) {
      var name = "q-" + q[0];
      qs.appendChild(el("div", { class: "yn", role: "radiogroup", "aria-labelledby": name + "-l" }, [
        el("span", { class: "q", id: name + "-l", text: q[1] }),
        el("span", { class: "choices" }, ["yes", "no"].map(function (v) {
          var id = name + "-" + v;
          var input = el("input", { type: "radio", name: name, id: id, value: v, checked: c.answers[q[0]] === v,
            onchange: function () { c.answers[q[0]] = v; flag(); } });
          return el("label", { for: id }, [input, v === "yes" ? "Yes" : "No"]);
        }))
      ]));
    });
    var flagNote = el("p", { class: "msg bad", "aria-live": "polite", style: "margin:0 0 12px" });
    function flag() {
      var a = c.answers;
      flagNote.textContent = (a.allergy === "yes" || a.eye === "yes" || a.surgery === "yes" || a.pregnant === "yes")
        ? "Thanks for telling us. Gabby will review this with you before she starts, and may suggest a patch test first." : "";
    }
    flag();

    var acks = el("fieldset", null, [el("legend", { text: "I acknowledge" })]);
    ACKS.forEach(function (a) {
      var id = "ack-" + a[0];
      acks.appendChild(el("div", { class: "check" }, [
        el("input", { type: "checkbox", id: id, checked: !!c.checks[a[0]], onchange: function (e) { c.checks[a[0]] = e.target.checked; } }),
        el("label", { for: id, text: a[1] })
      ]));
    });

    var typed = el("input", { type: "text", autocomplete: "name", value: c.typedName, oninput: function (e) { c.typedName = e.target.value; } });

    // Signature pad
    var canvas = el("canvas", { class: "sigpad", id: "sigpad", role: "img", tabindex: "0", "aria-label": "Signature pad. Draw your signature with a finger, stylus, or mouse." });
    var sigStatus = el("span", { class: "muted", style: "font-size:13px", "aria-live": "polite", text: c.signed ? "Signed" : "Sign above" });
    var sig = el("fieldset", null, [
      el("legend", { text: "Signature" }),
      field("f-typed", "Type your full name", typed),
      el("p", { style: "font-size:14px;color:var(--ink-soft);margin:4px 0 6px", text: "Draw your signature" }),
      el("div", { class: "sigpad-wrap" }, [canvas, el("span", { class: "sigpad-line", "aria-hidden": "true" }), el("span", { class: "sigpad-x", "aria-hidden": "true", text: "x" })]),
      el("div", { class: "sig-row" }, [sigStatus, el("button", { type: "button", class: "btn ghost small", text: "Clear", onclick: function () { clearPad(); } })])
    ]);

    var ctx, drawing = false, last = null;
    function setupPad() {
      var r = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(r.width * dpr));
      canvas.height = Math.max(1, Math.round(r.height * dpr));
      ctx = canvas.getContext("2d");
      ctx.scale(dpr, dpr);
      ctx.lineWidth = 2.4; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = "#1d1418";
      if (c.signed && c.sigData) {
        var img = new Image();
        img.onload = function () { ctx.drawImage(img, 0, 0, r.width, r.height); };
        img.src = c.sigData;
      }
    }
    function pos(e) { var r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
    canvas.addEventListener("pointerdown", function (e) {
      e.preventDefault();
      drawing = true; last = pos(e);
      try { canvas.setPointerCapture(e.pointerId); } catch (x) { /* older browsers */ }
      ctx.beginPath(); ctx.arc(last.x, last.y, 1.1, 0, Math.PI * 2); ctx.fillStyle = "#1d1418"; ctx.fill();
    });
    canvas.addEventListener("pointermove", function (e) {
      if (!drawing) return;
      var p = pos(e);
      ctx.beginPath(); ctx.moveTo(last.x, last.y); ctx.lineTo(p.x, p.y); ctx.stroke();
      last = p;
      if (!c.signed) { c.signed = true; sigStatus.textContent = "Signed"; }
    });
    function end() {
      if (!drawing) return;
      drawing = false;
      c.signed = true; sigStatus.textContent = "Signed";
      try { c.sigData = canvas.toDataURL("image/png"); } catch (x) { /* ignore */ }
    }
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);
    canvas.addEventListener("pointerleave", end);
    function clearPad() {
      ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.restore();
      c.signed = false; c.sigData = null; sigStatus.textContent = "Signature cleared. Sign above.";
    }
    setTimeout(setupPad, 0);

    var view = shell("Consent form", "Required once a year for lash extensions. It takes about a minute.", [text, qs, flagNote, acks, sig], actionRow({
      onNext: function () {
        for (var i = 0; i < QUESTIONS.length; i++) {
          if (!c.answers[QUESTIONS[i][0]]) { document.getElementById("q-" + QUESTIONS[i][0] + "-yes").focus(); return showErr("Answer every health question (yes or no)."); }
        }
        for (var j = 0; j < ACKS.length; j++) {
          if (!c.checks[ACKS[j][0]]) { document.getElementById("ack-" + ACKS[j][0]).focus(); return showErr("Check each acknowledgement to continue."); }
        }
        if (c.typedName.trim().length < 2) { typed.focus(); return showErr("Type your full name as your signature."); }
        if (!c.signed) { canvas.focus(); return showErr("Draw your signature in the box."); }
        c.signedNow = true;
        next();
      }
    }));
    return view;
  }

  // ---------- 5. review & pay ----------
  function renderPay() {
    var s = svc();
    var isNew = !draft.client;
    var p = pricing();

    function row(label, value, cls) { return el("tr", { class: cls || null }, [el("th", { scope: "row", text: label }), el("td", { text: value })]); }
    var table = el("table", { class: "sum" }, [el("caption", { style: "position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)", text: "Booking summary" }), el("tbody", null, [
      row("Service", s.name),
      row("Date", longDate(draft.date)),
      row("Time", GG.label(draft.start) + " (" + dur(s.minutes) + ")"),
      row("Price", p.price == null ? "Set at consultation" : money(p.price)),
      p.fee ? row("After-hours fee", "+" + money(p.fee)) : null,
      p.discount ? row("Coupon " + draft.coupon.code, "-" + money(p.discount)) : null,
      row("Total", p.total == null ? "Set at consultation" : money(p.total), "total"),
      row("Deposit due now", money(GG.DEPOSIT), "due"),
      row("Balance at appointment", p.balance == null ? "Total minus $" + GG.DEPOSIT : money(p.balance))
    ].filter(Boolean))]);

    var code = el("input", { type: "text", id: "f-coupon", autocomplete: "off", spellcheck: "false", value: draft.couponCode, "aria-describedby": "coupon-msg" });
    var cmsg = el("p", { id: "coupon-msg", class: "msg" + (draft.coupon ? (draft.coupon.ok ? " ok" : " bad") : ""), "aria-live": "polite", text: draft.coupon ? draft.coupon.message : "" });
    var coupon = el("div", { class: "field", style: "margin-top:16px" }, [
      el("label", { for: "f-coupon", text: "Coupon code" }),
      el("div", { class: "coupon-row" }, [code, el("button", { type: "button", class: "btn ghost", text: "Apply", onclick: function () {
        draft.couponCode = code.value.trim().toUpperCase();
        var r = GG.applyCoupon(state, draft.couponCode, s.price, isNew);
        draft.coupon = r.ok ? { ok: true, code: draft.couponCode, discount: r.discount, message: r.message } : (r.message ? { ok: false, code: draft.couponCode, discount: 0, message: r.message } : null);
        render();
        var m = document.getElementById("coupon-msg"); if (m) { m.textContent = ""; m.textContent = draft.coupon ? draft.coupon.message : ""; }
        var f = document.getElementById("f-coupon"); if (f) f.focus();
      } })])
    , cmsg]);

    var payGrid = el("div", { class: "pay-grid", role: "radiogroup", "aria-label": "Deposit method" });
    METHODS.forEach(function (m) {
      var on = draft.method === m.key;
      payGrid.appendChild(el("button", {
        type: "button", role: "radio", class: "pay" + (m.key === "zelle" ? " wide" : ""), "aria-checked": String(on),
        onclick: function () { draft.method = m.key; render(); var b = document.querySelector('.pay[aria-checked="true"]'); if (b) b.focus(); }
      }, [m.name, el("small", { text: m.key === "zelle" ? "Confirmed by hand" : "Paid instantly through Square" })]));
    });
    var payNote = null;
    if (draft.method === "zelle") {
      payNote = el("div", { class: "pay-note", "aria-live": "polite" }, [
        "Send $" + GG.DEPOSIT + " to ", el("strong", { text: ZELLE_TO }), " via Zelle; Gabby confirms it by hand. Your booking is held as deposit pending until she does."
      ]);
    } else if (draft.method) {
      payNote = el("div", { class: "pay-note", "aria-live": "polite", text: "Paid instantly through Square. In this demo nothing is charged." });
    }

    var policies = el("div", { class: "card", style: "margin-top:18px", id: "policies-box" }, [
      el("h3", { class: "serif", style: "font-size:18px;margin-bottom:8px", text: "Before you confirm" }),
      el("ul", { class: "policy-list" }, [
        el("li", { text: "10-minute grace period. After that the appointment may be shortened or canceled." }),
        el("li", { text: "The $" + GG.DEPOSIT + " deposit is non-refundable and goes toward your total." }),
        el("li", { text: "Cancel or reschedule at least 24 hours ahead." })
      ])
    ]);

    var body = [
      el("div", { class: "card" }, [table, coupon]),
      el("h3", { class: "group-h", text: "Pay your $" + GG.DEPOSIT + " deposit" }),
      payGrid, payNote, policies
    ];
    return shell("Review and pay deposit", draft.consentOnFile ? "Consent on file. Check the details below." : "Check the details below.", body, actionRow({
      nextText: "Confirm booking",
      onNext: confirmBooking
    }));
  }

  function confirmBooking() {
    if (!draft.method) return showErr("Choose how you'll pay the deposit.");
    // Re-read the store and re-check the slot right before saving.
    state = GG.load();
    var free = GG.availableSlots(state, draft.date, draft.serviceId).indexOf(draft.start) !== -1;
    if (!free) {
      draft.start = null;
      showErr("Sorry, that time was just taken. Pick another time.");
      setTimeout(function () { go(1); showErr("That time was just taken. Pick another time."); }, 1600);
      return;
    }
    if (GG.isBanned(state, draft.phone, draft.email)) return renderStop();

    var client = GG.findClient(state, draft.phone, draft.email);
    var today = GG.iso(new Date());
    if (!client) {
      client = { id: GG.newId(state, "c"), name: draft.name.trim(), phone: digits(draft.phone), email: draft.email.trim().toLowerCase(),
        consentSignedAt: null, noShows: 0, banned: false, note: "" };
      state.clients.push(client);
    } else {
      client.name = draft.name.trim() || client.name;
      client.phone = digits(draft.phone) || client.phone;
      client.email = draft.email.trim().toLowerCase() || client.email;
    }
    if (draft.consent.signedNow) client.consentSignedAt = today;

    // Re-validate the coupon against the fresh store.
    var p = pricing(), couponCode = null;
    if (draft.coupon && draft.coupon.ok) {
      var r = GG.applyCoupon(state, draft.coupon.code, svc().price, !draft.client);
      if (r.ok) {
        couponCode = draft.coupon.code;
        state.coupons.forEach(function (c) { if (c.code === couponCode) c.uses = (c.uses || 0) + 1; });
      } else { draft.coupon = null; p = pricing(); }
    }

    var booking = {
      id: GG.newId(state, "b"), clientId: client.id, serviceId: draft.serviceId, date: draft.date, start: draft.start,
      status: "confirmed", deposit: draft.method, depositPaid: draft.method !== "zelle", coupon: couponCode, total: p.total
    };
    state.bookings.push(booking);
    GG.save(state);
    draft.booking = booking;
    go(5);
    announce("You're booked.");
  }

  // ---------- 6. done ----------
  function icsText(b) {
    var s = GG.service(b.serviceId);
    var startMin = GG.toMin(b.start), endMin = startMin + s.minutes;
    var d = b.date.replace(/-/g, "");
    function t(m) { return d + "T" + GG.fromMin(m).replace(":", "") + "00"; }
    var stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
    return [
      "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Gabbs Glamour//Demo//EN", "CALSCALE:GREGORIAN",
      "BEGIN:VEVENT",
      "UID:" + b.id + "-" + d + "@gabbsglamour.demo",
      "DTSTAMP:" + stamp,
      "DTSTART;TZID=America/Chicago:" + t(startMin),
      "DTEND;TZID=America/Chicago:" + t(endMin),
      "SUMMARY:" + s.name + " with Gabbs Glamour",
      "LOCATION:Tomball\\, TX",
      "DESCRIPTION:Arrive with clean lashes and no eye makeup. 10-minute grace period. Cancel at least 24 hours ahead.",
      "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY", "DESCRIPTION:Lash appointment tomorrow", "END:VALARM",
      "END:VEVENT", "END:VCALENDAR"
    ].join("\r\n") + "\r\n";
  }
  function downloadIcs(b) {
    var blob = new Blob([icsText(b)], { type: "text/calendar;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = el("a", { href: url, download: "gabbs-glamour-" + b.date + ".ics" });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function renderDone() {
    var b = draft.booking, s = GG.service(b.serviceId);
    var sms = "Gabbs Glamour: You're booked for " + s.name + " on " + shortDate(b.date) + " at " + GG.label(b.start) + ". Reply C to cancel. Reminder coming the day before.";
    var method = METHODS.filter(function (m) { return m.key === b.deposit; })[0].name;
    function row(label, value) { return el("tr", null, [el("th", { scope: "row", text: label }), el("td", { text: value })]); }

    var details = el("table", { class: "sum" }, [el("tbody", null, [
      row("Service", s.name),
      row("When", longDate(b.date) + ", " + GG.label(b.start)),
      row("Length", dur(s.minutes)),
      row("Total", b.total == null ? "Set at consultation" : money(b.total)),
      row("Deposit", money(GG.DEPOSIT) + " by " + method + (b.depositPaid ? ", paid" : ", pending")),
      b.coupon ? row("Coupon", b.coupon) : null,
      row("Balance at appointment", b.total == null ? "Total minus $" + GG.DEPOSIT : money(Math.max(0, b.total - GG.DEPOSIT)))
    ].filter(Boolean))]);

    var pending = b.depositPaid ? null : el("div", { class: "pay-note", style: "margin-top:14px" }, [
      el("span", { class: "chip warn", text: "Deposit pending" }), " ",
      "Send $" + GG.DEPOSIT + " to ", el("strong", { text: ZELLE_TO }), " via Zelle. Gabby confirms it by hand, then your spot is locked in."
    ]);

    var v = el("section", { class: "step", tabindex: "-1", "aria-labelledby": "step-h" }, [
      el("div", { class: "done-head" }, [
        el("p", { class: "script", style: "font-size:40px;margin:0", text: "see you soon" }),
        el("h2", { id: "step-h", class: "step-title", text: "You're booked!" }),
        el("p", { class: "muted", style: "margin:4px 0 18px", text: "A confirmation text is on its way to " + formatPhone(draft.phone) + "." })
      ]),
      el("div", { class: "card" }, [details, pending]),
      el("h3", { class: "group-h", text: "Your text confirmation" }),
      el("div", { class: "phone-mock", role: "img", "aria-label": "Text message preview: " + sms }, [
        el("p", { class: "from", text: "Text message · Gabbs Glamour" }),
        el("p", { class: "bubble", style: "margin:0", text: sms })
      ]),
      el("div", { class: "actions" }, [
        el("a", { class: "btn ghost", href: "./", text: "Back to home" }),
        el("button", { type: "button", class: "btn", id: "ics-btn", text: "Add to calendar", onclick: function () { downloadIcs(b); } })
      ]),
      el("div", { class: "card", style: "margin-top:18px" }, [
        el("h3", { class: "serif", style: "font-size:18px;margin-bottom:6px", text: "Manage booking" }),
        el("p", { class: "soft", style: "margin:0;font-size:15px", text: "To cancel, reply C to your confirmation text. To reschedule, use the link in that text or contact Gabby. Please give at least 24 hours notice; the deposit is non-refundable." })
      ])
    ]);
    return v;
  }
  function formatPhone(p) {
    var d = digits(p).slice(-10);
    return d.length === 10 ? "(" + d.slice(0, 3) + ") " + d.slice(3, 6) + "-" + d.slice(6) : p;
  }

  // ---------- petals ----------
  function petals() {
    var box = document.getElementById("petals");
    if (!box) return;
    for (var i = 0; i < 9; i++) {
      var p = el("span", { class: "petal" });
      p.style.left = (5 + i * 11 + (i % 3) * 2) + "%";
      p.style.animationDuration = (9 + (i % 4) * 2.5) + "s";
      p.style.animationDelay = (-i * 1.7) + "s";
      p.style.transformOrigin = "center";
      p.style.scale = String(0.7 + (i % 3) * 0.2);
      box.appendChild(p);
    }
  }

  // ---------- boot ----------
  var want = new URLSearchParams(location.search).get("service");
  if (want && GG.service(want)) draft.serviceId = want;
  petals();
  render();
})();
