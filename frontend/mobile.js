/* Sidebar toggle, both form factors.
 *
 * Injected at serve time next to mobile.css (index.html on disk stays
 * pristine -- see the no-fork note in docs/HOSTING.md).
 *
 *   phone  (<=768px): aside is a slide-in drawer over a backdrop
 *   desktop (>768px): aside collapses left, content widens; state persists
 *
 * The page hydrates asynchronously (support.js renders into <x-dc>), so the
 * aside does not exist at DOMContentLoaded. Poll briefly, then give up
 * quietly -- no button just means the always-visible desktop layout.
 */
(function () {
  var tries = 0;
  var PHONE_MQ = '(max-width: 768px), ((pointer: coarse) and (max-height: 500px))';
  var phone = function () { return matchMedia(PHONE_MQ).matches; };

  function init() {
    var aside = document.querySelector('aside');
    if (!aside) {
      if (tries++ < 600) requestAnimationFrame(init);
      return;
    }
    if (document.getElementById('fb-menu-btn')) return;

    var btn = document.createElement('button');
    btn.id = 'fb-menu-btn';
    btn.setAttribute('aria-label', 'Toggle menu');
    btn.textContent = '☰';

    var backdrop = document.createElement('div');
    backdrop.id = 'fb-backdrop';

    btn.addEventListener('click', function () {
      if (phone()) {
        document.body.classList.toggle('fb-menu-open');
      } else {
        var collapsed = document.body.classList.toggle('fb-side-collapsed');
        try { localStorage.setItem('fb_side_collapsed', collapsed ? '1' : ''); } catch (e) {}
      }
    });
    backdrop.addEventListener('click', function () {
      document.body.classList.remove('fb-menu-open');
    });

    // Installed as a PWA there is no browser chrome: any link that navigates
    // the app itself away leaves the user stranded with no back button
    // ("player details didn't let me go back"). External links therefore
    // open outside the shell; the app never leaves itself.
    document.addEventListener('click', function (event) {
      var a = event.target.closest && event.target.closest('a[href]');
      if (!a) return;
      var href = a.getAttribute('href') || '';
      if (/^https?:/i.test(href)) {
        try {
          if (new URL(href).origin !== location.origin) {
            event.preventDefault();
            window.open(href, '_blank', 'noopener');
          }
        } catch (e) {}
      }
    }, true);

    // Capture phase: the page's own nav handling stops propagation, which is
    // why a bubble listener on the aside never saw the click.
    document.addEventListener('click', function (event) {
      if (phone() && event.target.closest && event.target.closest('aside nav button')) {
        document.body.classList.remove('fb-menu-open');
      }
    }, true);

    function applyMode() {
      // Rotation crosses the phone/desktop boundary; stale classes from the
      // other mode make the layout lie. Reset, then restore what applies.
      document.body.classList.remove('fb-menu-open');
      document.body.classList.remove('fb-side-collapsed');
      try {
        if (!phone() && localStorage.getItem('fb_side_collapsed') === '1') {
          document.body.classList.add('fb-side-collapsed');
        }
      } catch (e) {}
    }
    matchMedia(PHONE_MQ).addEventListener('change', applyMode);
    applyMode();

    document.body.appendChild(backdrop);
    document.body.appendChild(btn);
  }

  init();
})();

/* Live-overlay decorations, same no-fork rule as the drawer above.
 *
 * The served data/feeds.json carries two things the page's template does not
 * render: `first_seen` on each news entry, and `injury_wire` -- the freshest
 * wire mention per player on the Out & returning tab. This paints both onto
 * the rendered rows:
 *
 *   news rows    a NEW badge on stories that arrived since the last visit
 *   injury rows  "Wire · Fri Aug 15 · 9:40 AM · ESPN — headline" (linked),
 *                or an honest "no wire mention" when the feed has none
 *
 * The page re-renders whole screens on navigation, so decoration re-applies
 * via a MutationObserver and must stay idempotent -- inserted nodes carry
 * marker classes and rows are skipped once stamped.
 */
(function () {
  var data = null;
  var prevVisit = '';

  /* A "visit" survives reloads for 30 minutes: refreshing mid-read must not
   * wipe the badges that brought you to the tab. */
  try {
    var visit = JSON.parse(localStorage.getItem('fb_visit') || '{}');
    var now = Date.now();
    // A corrupted stamp must rotate like a missing one, or NaN comparisons
    // freeze the session forever and badges compare against ancient state.
    if (visit.cur && isNaN(Date.parse(visit.cur))) visit.cur = '';
    if (!visit.cur || now - Date.parse(visit.cur) > 30 * 60 * 1000) {
      visit.prev = visit.cur || '';
      visit.cur = new Date(now).toISOString();
      localStorage.setItem('fb_visit', JSON.stringify(visit));
    }
    prevVisit = visit.prev || '';
  } catch (e) {}

  var pending = false;
  function schedule() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () { pending = false; decorate(); });
  }

  /* Pulled at load and again on wake: an installed app instance can sit
   * in memory for weeks, and a copy fetched once at startup quietly ages
   * into last month's wire (owner hit this Sep 1 — three tabs "stuck on
   * Aug 14th" while the server was fresh). Throttled to once per five
   * minutes; a failed re-pull keeps what is on screen, same as the page's
   * own fallback. */
  var pulledAt = 0;
  function pullFeeds() {
    pulledAt = Date.now();
    // Absolute path + no-store for the same reason the page's own puller
    // uses them: a relative path can misresolve under an installed-app
    // scope, and a stale intermediary must not stand in for the live wire.
    fetch('/app/data/feeds.json', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (f) { if (f) { data = f; schedule(); } })
      .catch(function () {});
  }
  pullFeeds();

  function wakeFeeds() {
    if (document.visibilityState !== 'visible') return;
    if (Date.now() - pulledAt < 5 * 60 * 1000) return;
    pullFeeds();
  }
  document.addEventListener('visibilitychange', wakeFeeds);
  window.addEventListener('focus', wakeFeeds);

  function newTexts() {
    /* First-ever visit: everything would be "new", which marks nothing. */
    var map = {};
    if (!prevVisit) return map;
    (data.news || []).forEach(function (n) {
      if (n.first_seen && n.first_seen > prevVisit) map[n.text] = true;
    });
    return map;
  }

  function badgeNews() {
    var fresh = newTexts();
    /* The news body div is the only 72ch element; exact text match keeps
     * accidental style twins harmless. */
    var bodies = document.querySelectorAll('div[style*="72ch"]');
    for (var i = 0; i < bodies.length; i++) {
      var el = bodies[i];
      if (!fresh[el.textContent] || el.querySelector('.fb-new-badge')) continue;
      var badge = document.createElement('span');
      badge.className = 'fb-new-badge';
      badge.textContent = 'NEW';
      el.insertBefore(badge, el.firstChild);
    }
  }

  function stampInjury() {
    var wire = data.injury_wire || {};
    /* Scope to the injury tab via its section header, so a player's name on
     * some other screen never grows a wire stamp. */
    var root = null;
    var headers = document.querySelectorAll('div[style*="0.14em"]');
    for (var i = 0; i < headers.length; i++) {
      if (headers[i].textContent === 'Out for season / PUP') {
        root = headers[i].closest('div[style*="grid-template-columns"]');
        break;
      }
    }
    if (!root) return;

    var names = root.querySelectorAll('span[style*="-0.02em"]');
    for (var j = 0; j < names.length; j++) {
      var row = names[j].parentElement && names[j].parentElement.parentElement;
      if (!row || row.querySelector('.fb-wire-stamp')) continue;
      var rowName = names[j].textContent.trim();
      var info = wire[rowName];
      var stamp = document.createElement('div');
      stamp.className = 'fb-wire-stamp';
      /* Sleeper's CURRENT flag beside the curated status (Aug 29). The
       * map is three-valued like the wire stamps: a flag string, "" for
       * indexed-but-unflagged (the cut-down-day signal), and absent for
       * a name the index cannot resolve -- which says nothing rather
       * than something invented. */
      var statuses = data.injury_status;
      if (statuses && (rowName in statuses)) {
        var live = document.createElement('span');
        live.textContent = 'Sleeper now: ' + (statuses[rowName] || 'no injury flag') + ' · ';
        stamp.appendChild(live);
      }
      if (info) {
        var text = 'Wire ' + (info.time ? '· ' + info.time + ' ' : '') +
          (info.source ? '· ' + info.source + ' ' : '') + '— ' + info.head;
        if (info.link) {
          var a = document.createElement('a');
          a.href = info.link;
          a.target = '_blank';
          a.rel = 'noopener';
          a.textContent = text;
          stamp.appendChild(a);
        } else {
          stamp.appendChild(document.createTextNode(text));
        }
      } else if (data && ('injury_wire' in data)) {
        /* The negative is only a measurement when the server actually
         * checked: injury_wire present-but-empty means "checked, quiet",
         * while an absent key means no poll has run -- claiming 21
         * quiet days off the bundled file would be an unmeasured
         * measurement. appendChild, not textContent: assignment would
         * wipe the Sleeper-status span prepended above. */
        stamp.appendChild(document.createTextNode('No wire mention in the last 21 days'));
      } else {
        stamp.appendChild(document.createTextNode('Wire check pending — no poll yet'));
      }
      row.appendChild(stamp);
    }
  }

  /* The Draft analyzer gains links to the mock draft room (owner request,
   * Aug 20: simulate the draft from their exact slot) and to league
   * settings (Aug 21: let users adjust their own league). Anchored on the
   * screen's own "My team" header so they only ever render there; both
   * open in a new tab because in-shell navigation strands the PWA (see
   * above). */
  var DRAFT_LINKS = [
    ['fb-mock-link', '/app/mock', 'Mock draft room — simulate from your slot →'],
    ['fb-leagues-link', '/app/leagues', 'League settings — score with your own rules →'],
    ['fb-nextup-link', '/app/nextup', 'Next man up — who to grab when a starter is out →'],
    ['fb-score-link', '/app/scorecard', 'Scorecard — how these calls actually did →'],
    ['fb-scoring-link', '/app/scoring', 'Scoring board — who scores most in each league →'],
    ['fb-idpweek-link', '/app/idpweek', 'IDP tracker — this week’s projected tacklers →']
  ];

  function linkDraftTools() {
    if (document.getElementById('fb-mock-link')) return;
    var headers = document.querySelectorAll('div[style*="0.14em"]');
    for (var i = 0; i < headers.length; i++) {
      if (headers[i].textContent.indexOf('My team') !== 0) continue;
      DRAFT_LINKS.forEach(function (spec) {
        var a = document.createElement('a');
        a.id = spec[0];
        a.href = spec[1];
        a.target = '_blank';
        a.rel = 'noopener';
        a.textContent = spec[2];
        headers[i].parentElement.insertBefore(a, headers[i]);
      });
      return;
    }
  }

  /* --- Sleepers: the owner's own list, and the wire about it -------------
   *
   * Owner, Aug 25: "maybe the sleepers need a list of people that i can
   * add but we also show sleepers alerts in seperate thread where we
   * search for new articles on sleepers for ppr leagues", and plainly,
   * "right now it doesnt make sense and this list should be editble".
   *
   * The tab shipped as 19 rows transcribed by hand from PFF, Yahoo and
   * Bleacher Report on Aug 14 and frozen: somebody else's picks, from
   * before the preseason, unchangeable. This replaces that panel with a
   * list you keep and a thread of the real polled items mentioning it.
   *
   * The thread is a join the server already had -- every item carries
   * the players it mentions -- so nothing is searched and nothing is
   * summarised. Titles link out to the real article. */
  var sleeperData = null;
  var sleeperBusy = false;

  function sleeperPost(p) {
    var row = document.createElement('div');
    row.className = 'fb-sl-post';
    var a = document.createElement('a');
    a.href = p.url || '#';
    a.target = '_blank';
    a.rel = 'noopener';
    a.className = 'fb-sl-title';
    a.textContent = p.title || '(untitled)';
    var meta = document.createElement('div');
    meta.className = 'fb-sl-meta';
    /* Who it is about, then where it came from and when. Every one of
     * these came off the item itself. */
    meta.textContent = (p.about || []).join(', ') + ' · ' + (p.source || '') +
      (p.published ? ' · ' + String(p.published).slice(0, 10) : '');
    row.appendChild(a);
    row.appendChild(meta);
    return row;
  }

  function sleeperRow(w) {
    var row = document.createElement('div');
    row.className = 'fb-src-row';
    var name = document.createElement('span');
    name.className = 'fb-src-name';
    name.textContent = w.name;
    var meta = document.createElement('span');
    meta.className = 'fb-src-meta';
    /* "no alerts yet" is a real answer to what a sleeper list asks, and
     * often the point of one -- so it is said, not hidden. A name the
     * player index does not carry is flagged, because it will never
     * collect wire and the reader should know why. */
    meta.textContent = w.known
      ? (w.meta ? w.meta + ' · ' : '') +
        (w.alerts ? w.alerts + (w.alerts === 1 ? ' alert' : ' alerts') : 'no alerts yet')
      : 'not a name the player index knows — no wire will match it';
    var drop = document.createElement('button');
    drop.className = 'fb-src-btn';
    drop.type = 'button';
    drop.textContent = 'Remove';
    drop.onclick = function () { editSleeper(w.name, true, drop); };
    row.appendChild(name);
    row.appendChild(meta);
    row.appendChild(drop);
    return row;
  }

  function editSleeper(name, drop, btn) {
    if (sleeperBusy) return;
    sleeperBusy = true;
    if (btn) btn.disabled = true;
    var body = new URLSearchParams();
    body.set('name', name);
    body.set('drop', drop ? '1' : '0');
    fetch('/app/mine/sleepers', {
      method: 'POST', credentials: 'same-origin', body: body,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    })
      .then(function (r) {
        if (r.status === 401) throw new Error('signed out');
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (fresh) {
        sleeperData = fresh;
        sleeperBusy = false;
        renderSleepers();
        /* The page keeps its own copy of this list, because its star
         * buttons render from component state. Hand it the new one so a
         * player added here wears a star over there without a reload --
         * one list, two places it is drawn. */
        if (typeof window.__fbSetSleepers === 'function') {
          window.__fbSetSleepers((fresh.watched || []).map(function (w) { return w.name; }));
        }
      })
      .catch(function (err) {
        sleeperBusy = false;
        if (btn) btn.disabled = false;
        sleeperNote(err.message === 'signed out'
          ? 'Sign in to keep a sleepers list.'
          : 'Could not save that — the list is unchanged.');
      });
  }

  function sleeperNote(text) {
    var host = document.getElementById('fb-sleepers');
    if (!host) return;
    var line = host.querySelector('.fb-src-msg');
    if (!line) {
      line = document.createElement('div');
      line.className = 'fb-src-msg';
      host.appendChild(line);
    }
    line.textContent = text;
  }

  /* What the panel actually shows. The MutationObserver re-runs decorate()
   * on every DOM change -- including the ones this render makes -- so an
   * unconditional rebuild would loop at frame rate and, worse, wipe a
   * half-typed name out of the add box on every pass. Rendering is
   * therefore a no-op unless the data behind it changed. */
  function sleeperStamp(d) {
    return JSON.stringify([
      (d.watched || []).map(function (w) { return w.name + '/' + w.alerts + '/' + w.known; }),
      (d.alerts || []).map(function (p) { return p.url || p.title; }),
      d.consensus
        ? (d.consensus.fetched_at || '') + '/' + (d.consensus.players || []).length
        : ''
    ]);
  }

  /* --- Community consensus: what the wire is recommending ---------------
   *
   * The other half of the owner's Aug 25 ask: a thread that SEARCHES the
   * wire for sleeper talk, not just the wire about players already on
   * the list. A nightly job reads full articles from the fantasy
   * publishers, has the AI reader classify each author's actual stance,
   * and blends the positive calls with Sleeper's add/drop trends into
   * one ranked list (scripts/fetch_sleepers.py).
   *
   * Honesty rules, same as everywhere: the section only exists when a
   * push has landed (no empty frame under a live-sounding heading), it
   * wears the date it was measured, every one-liner is labelled as the
   * AI reader's paraphrase, and the links go to the real articles. */

  /* Ranked already, so the tail is noise on a phone; the tap-out links
   * carry anyone who wants the rest. */
  var CONSENSUS_SHOWN = 12;

  function consensusRow(p) {
    var row = document.createElement('div');
    row.className = 'fb-cs-row';
    var name = document.createElement('div');
    name.className = 'fb-cs-name';
    var who = [p.position, p.team].filter(Boolean).join(' · ');
    name.textContent = p.name + (who ? ' · ' + who : '');
    row.appendChild(name);
    var meta = document.createElement('div');
    meta.className = 'fb-cs-meta';
    var bits = [
      p.source_count + (p.source_count === 1 ? ' source' : ' sources'),
      p.mention_count + (p.mention_count === 1 ? ' call' : ' calls')
    ];
    /* Dissent is shown, never averaged away: "three sites love him, one
     * is out" is a finding, and hiding the one would be a false positive
     * about the agreement. */
    if (p.dissent_count) bits.push(p.dissent_count + ' against');
    if (p.trending_adds_72h) bits.push(p.trending_adds_72h + ' Sleeper adds/72h');
    if (p.roster_pct) bits.push(p.roster_pct + '% rostered');
    meta.textContent = bits.join(' · ');
    row.appendChild(meta);
    if ((p.reasons || []).length) {
      var why = document.createElement('div');
      why.className = 'fb-cs-why';
      /* The model's own paraphrase, labelled as such -- same rule as the
       * "AI angle:" capsules. Never a quote from the article. */
      why.textContent = 'AI read: ' + p.reasons[0];
      row.appendChild(why);
    }
    if ((p.links || []).length) {
      var links = document.createElement('div');
      links.className = 'fb-cs-links';
      p.links.forEach(function (l) {
        var a = document.createElement('a');
        a.href = l.url;
        a.target = '_blank';
        a.rel = 'noopener';
        a.className = 'fb-cs-link';
        a.textContent = l.source || 'article';
        a.title = l.title || '';
        links.appendChild(a);
      });
      row.appendChild(links);
    }
    return row;
  }

  function consensusSection(c) {
    if (!c || !(c.players || []).length) return null;
    var wrap = document.createElement('div');
    wrap.className = 'fb-sl-thread fb-cs';
    var head = document.createElement('div');
    head.className = 'fb-src-head';
    head.textContent = 'Community consensus · who the wire is recommending';
    wrap.appendChild(head);
    var note = document.createElement('div');
    note.className = 'fb-src-note';
    /* The as-of stamp is the data's own fetch time, never a typed date --
     * the lesson every kicker in the app has already paid for. */
    note.textContent = 'AI-read from ' + (c.article_count || 0) + ' articles across ' +
      (c.sources_surveyed || []).length + ' feeds · as of ' +
      String(c.fetched_at || '').slice(0, 10);
    wrap.appendChild(note);
    (c.players || []).slice(0, CONSENSUS_SHOWN).forEach(function (p) {
      wrap.appendChild(consensusRow(p));
    });
    if (c.attribution) {
      var foot = document.createElement('div');
      foot.className = 'fb-src-foot';
      foot.textContent = c.attribution;
      wrap.appendChild(foot);
    }
    return wrap;
  }

  function renderSleepers() {
    var host = document.getElementById('fb-sleepers');
    if (!host || !sleeperData) return;
    var stamp = sleeperStamp(sleeperData);
    if (host.getAttribute('data-stamp') === stamp) return;
    host.setAttribute('data-stamp', stamp);
    /* Carry the half-typed name across a refresh that lands mid-sentence. */
    var box = host.querySelector('.fb-sl-add input');
    var typed = box && box.value ? box.value : '';
    host.textContent = '';

    var head = document.createElement('div');
    head.className = 'fb-src-head';
    var n = (sleeperData.watched || []).length;
    head.textContent = 'My sleepers · ' + n + (n === 1 ? ' player' : ' players') +
      ' · ' + (sleeperData.alerts || []).length + ' alerts about them';
    host.appendChild(head);

    var form = document.createElement('form');
    form.className = 'fb-sl-add';
    var input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Add a player by name';
    input.setAttribute('aria-label', 'Add a player to your sleepers list');
    var go = document.createElement('button');
    go.className = 'fb-src-btn';
    go.type = 'submit';
    go.textContent = 'Add';
    form.onsubmit = function (e) {
      e.preventDefault();
      var v = input.value.trim();
      if (v) { input.value = ''; editSleeper(v, false, go); }
    };
    input.value = typed;
    form.appendChild(input);
    form.appendChild(go);
    host.appendChild(form);

    (sleeperData.watched || []).forEach(function (w) { host.appendChild(sleeperRow(w)); });

    if (!n) {
      var empty = document.createElement('div');
      empty.className = 'fb-src-note';
      /* An empty list is a legitimate state and says so, rather than the
       * tab looking broken. */
      empty.textContent = 'Nobody on the list yet. Add a player and every ' +
        'alert that mentions him shows up here.';
      host.appendChild(empty);
      /* No list is exactly when the consensus earns its keep: it is the
       * place to start one from. */
      var starter = consensusSection(sleeperData.consensus);
      if (starter) host.appendChild(starter);
      return;
    }

    var thread = document.createElement('div');
    thread.className = 'fb-sl-thread';
    var th = document.createElement('div');
    th.className = 'fb-src-head';
    th.textContent = 'Alerts about them';
    thread.appendChild(th);
    if (!(sleeperData.alerts || []).length) {
      var none = document.createElement('div');
      none.className = 'fb-src-note';
      none.textContent = 'No alerts about these players yet. That is an ' +
        'answer too — a sleeper nobody is writing about is still a sleeper.';
      thread.appendChild(none);
    } else {
      sleeperData.alerts.forEach(function (p) { thread.appendChild(sleeperPost(p)); });
    }
    host.appendChild(thread);

    var consensus = consensusSection(sleeperData.consensus);
    if (consensus) host.appendChild(consensus);
  }

  var sleeperFetched = false;

  /* A star clicked elsewhere on the page writes to the server itself and
   * says so. Without this the panel would keep showing the list as it
   * stood when the tab opened -- the same two-lists confusion, one
   * session long instead of forever. */
  window.addEventListener('fb-sleepers-changed', function () {
    sleeperData = null;
    sleeperFetched = false;
    showSleepers();
  });

  function showSleepers() {
    /* Navigating away re-renders the screen and takes the host with it, so
     * the anchor is looked up again every pass rather than once at boot. */
    if (!document.getElementById('fb-sleepers')) {
      var anchor = document.querySelector('[data-fb-sleepers]');
      if (!anchor || !anchor.parentElement) return;
      var host = document.createElement('div');
      host.id = 'fb-sleepers';
      anchor.parentElement.insertBefore(host, anchor);
    }
    if (sleeperData) { renderSleepers(); return; }
    if (sleeperFetched) return;
    sleeperFetched = true;
    fetch('/app/data/sleepers.json', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) { sleeperData = d; renderSleepers(); } })
      .catch(function () { /* the analysts' table stays; silence is right */ });
  }

  /* Club themes (owner, Aug 21). The page owns its own theme state and
   * writes ww_theme; this mirrors that choice onto <html>, where the
   * club palettes in /app/teams.css live, so switching modes repaints
   * immediately instead of on the next load. Also offers the club
   * chooser once, to someone who has never picked one. */
  function applyTeamTheme() {
    var t, club;
    try {
      t = localStorage.getItem('ww_theme') || 'team';
      club = localStorage.getItem('fb_team') || '';
    } catch (e) { return; }
    var legacy = { cowboys: 'DAL', titans: 'TEN' };
    if (legacy[t]) { club = club || legacy[t]; t = 'team'; }
    var root = document.documentElement;
    if (t === 'light') { delete root.dataset.theme; } else { root.dataset.theme = t; }
    if (t === 'team' && club) { root.dataset.team = club; } else { delete root.dataset.team; }
  }

  function offerTeamPicker() {
    var picked;
    try { picked = localStorage.getItem('fb_team'); } catch (e) { return; }
    if (picked || document.getElementById('fb-team-ask')) return;
    var bar = document.createElement('div');
    bar.id = 'fb-team-ask';
    /* Owner, Aug 21: "choose your team should be in middle of page so I
       can see it." It was a 12px strip pinned to the bottom edge, among
       the sync footer and the menu button, and it read as chrome rather
       than a question. Same one-time ask, now a centred panel. */
    bar.setAttribute('role', 'dialog');
    bar.setAttribute('aria-modal', 'true');
    bar.setAttribute('aria-label', 'Choose your team');
    bar.innerHTML = "<div class='fb-team-ask-card'>" +
      "<img src='/app/assets/fsb-mark.svg' alt='' width='104' height='80'>" +
      "<h2>Choose your team</h2>" +
      "<p>Pick a club and the whole app wears its colours \u2014 the " +
      "boards, the mock room, all of it.</p>" +
      "<a href='/app/mine'>Choose a team →</a>" +
      "<button type='button'>Not now</button></div>";
    bar.querySelector('button').onclick = function () {
      /* Remembered as the house theme, so the ask does not come back
         every visit for someone who does not want a club. */
      try { localStorage.setItem('fb_team', 'FSB'); } catch (e) {}
      bar.remove();
      applyTeamTheme();
    };
    document.body.appendChild(bar);
  }

  /* How the Draft analyzer's average is made (owner request, Aug 21:
   * the source list "should probably belong in the draft analyzer so
   * they know how the average is created", and they want to "see live
   * updates when one is added or removed").
   *
   * The server injects the current set as FB_RANK_SOURCES when it builds
   * the page, so the first paint is already right. A list is added or
   * removed at /app/mine though -- a different tab -- so coming back here
   * would otherwise show the set from whenever this tab last loaded.
   * Hence the re-read on focus.
   *
   * Lists that are switched OFF are shown too, greyed. "Why is this
   * source not counting" is the question a panel showing only the active
   * ones cannot answer, and it is the question that started this.
   *
   * Anchored on the analyzer's "Board order" row, which is a serve-time
   * rename (app/feeds/page.py source_truth) -- the committed document
   * still says "Source influence". Match the served page, not the file. */
  var sources = (typeof FB_RANK_SOURCES !== 'undefined' && FB_RANK_SOURCES) || null;
  var sourcesFetching = false;

  /* Where "old enough to distrust" falls. Preseason is when depth charts
   * and injuries redraw a board, and a top-300 sheet written before the
   * games is describing a different league. Chosen, not measured -- so it
   * is recorded in docs/ASSUMPTIONS.md and shown as a note rather than
   * used to switch anything off. */
  var STALE_DAYS = 21;

  function ageWords(days) {
    if (days <= 0) return 'today';
    if (days === 1) return '1 day old';
    return days + ' days old';
  }

  function sourceRow(s) {
    var row = document.createElement('div');
    row.className = 'fb-src-row' + (s.active ? '' : ' fb-src-off');
    var name = document.createElement('span');
    name.className = 'fb-src-name';
    name.textContent = s.name;
    var meta = document.createElement('span');
    meta.className = 'fb-src-meta';
    /* Every number here came off the list itself. Nothing is estimated,
     * so nothing needs a hedge. */
    var bits = [s.n + ' players', 'as of ' + s.asOf + ' · ' + ageWords(s.age)];
    if (s.scope && s.scope !== 'OVERALL') bits.push('ranks within ' + s.scope);
    /* The reason the owner wanted these controls: "they olderones may get
     * outdated based on preseason". A date is already shown, but a date
     * is something you have to do arithmetic on. STALE_DAYS is a judgement
     * and is written down as one -- see docs/ASSUMPTIONS.md. The row says
     * it plainly and still leaves the decision to the reader; nothing is
     * switched off automatically. */
    if (s.age >= STALE_DAYS) {
      row.className += ' fb-src-stale';
      bits.push('preseason has moved since this');
    }
    meta.textContent = bits.join(' · ');
    /* The control, on the board rather than a tab away (owner, Aug 25:
     * "i need a way to add or remove all top 300 list default and added
     * from draft page ... they olderones may get outdated based on
     * preseason"). Built-in and uploaded lists get the same button,
     * because from here they are the same thing: a list that is counting
     * when it should not be. */
    var toggle = document.createElement('button');
    toggle.className = 'fb-src-btn';
    toggle.type = 'button';
    toggle.textContent = s.active ? 'in the average' : 'off';
    toggle.title = s.active ? 'Switch this list out of the blend'
                            : 'Switch this list into the blend';
    toggle.setAttribute('aria-pressed', s.active ? 'true' : 'false');
    toggle.onclick = function () { setActive(s.key, !s.active, toggle); };
    row.appendChild(name);
    row.appendChild(meta);
    row.appendChild(toggle);
    return row;
  }

  /* Posts the change and re-renders from the response, so the panel shows
   * what the SERVER now holds rather than what this tab guessed. The
   * board's own blend is rebuilt on the next page load; the panel says so
   * rather than pretending the order under it has already moved. */
  function setActive(key, on, btn) {
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    var body = new URLSearchParams();
    body.set('key', key);
    body.set('on', on ? '1' : '0');
    fetch('/app/mine/list/active', {
      method: 'POST', credentials: 'same-origin', body: body,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    })
      .then(function (r) {
        if (r.status === 401) throw new Error('signed out');
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (fresh) {
        if (!Array.isArray(fresh)) throw new Error('bad payload');
        sources = fresh;
        renderSources();
        note('Saved — the board picks it up on the next load.');
      })
      .catch(function (err) {
        /* Never leave a button that looks like it worked. The old state
         * is still on screen and the reason is said out loud. */
        btn.disabled = false;
        note(String(err.message) === 'signed out'
          ? 'Sign in to change which lists count.'
          : 'Could not save that — the list is unchanged.');
      });
  }

  /* Sequential, not Promise.all: each response carries the whole set,
   * so parallel writes would race and the panel would render whichever
   * reply landed last rather than the final state. Slower and correct. */
  function setAll(on, btn) {
    var todo = sources.filter(function (s) { return s.active !== on; })
                      .map(function (s) { return s.key; });
    if (!todo.length) { note(on ? 'All lists are already on.' : 'All lists are already off.'); return; }
    btn.disabled = true;
    var i = 0;
    function step() {
      if (i >= todo.length) {
        btn.disabled = false;
        renderSources();
        note('Saved — the board picks it up on the next load.');
        return;
      }
      var body = new URLSearchParams();
      body.set('key', todo[i++]);
      body.set('on', on ? '1' : '0');
      fetch('/app/mine/list/active', {
        method: 'POST', credentials: 'same-origin', body: body,
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (fresh) { if (Array.isArray(fresh)) sources = fresh; step(); })
        .catch(function () {
          btn.disabled = false;
          renderSources();
          note('Stopped part way — some lists are unchanged.');
        });
    }
    step();
  }

  function note(text) {
    var host = document.getElementById('fb-rank-sources');
    if (!host) return;
    var line = host.querySelector('.fb-src-msg');
    if (!line) {
      line = document.createElement('div');
      line.className = 'fb-src-msg';
      host.appendChild(line);
    }
    line.textContent = text;
  }

  function renderSources() {
    var host = document.getElementById('fb-rank-sources');
    if (!host || !sources) return;
    var active = sources.filter(function (s) { return s.active; });
    host.textContent = '';

    var head = document.createElement('div');
    head.className = 'fb-src-head';
    head.textContent = 'How the average is made · ' + active.length +
      ' of ' + sources.length + ' lists in the blend';
    host.appendChild(head);

    var note = document.createElement('div');
    note.className = 'fb-src-note';
    /* The honest description of blend() -- equal weight, averaged over
     * the lists that carry the player, no invented rank for the ones
     * nobody lists. Anything shorter would be a claim about weights that
     * no longer exist. */
    note.textContent = active.length
      ? 'Every list switched on counts the same. A player’s blended rank is his ' +
        'average place across the lists that carry him — a shorter list does not ' +
        'push him down, and a player no list ranks gets no blended rank at all.'
      : 'No list is switched on, so nothing is being averaged. The board is in its ' +
        'own order.';
    host.appendChild(note);

    sources.forEach(function (s) { host.appendChild(sourceRow(s)); });

    /* One control for all of them, which is the shape the owner asked for
     * -- "that way we can turn off and on from one part". Switching every
     * list off is a legitimate state (the board falls back to its own
     * order) so it is offered rather than guarded against. */
    var bulk = document.createElement('div');
    bulk.className = 'fb-src-bulk';
    [['All on', true], ['All off', false]].forEach(function (spec) {
      var b = document.createElement('button');
      b.className = 'fb-src-btn';
      b.type = 'button';
      b.textContent = spec[0];
      b.onclick = function () { setAll(spec[1], b); };
      bulk.appendChild(b);
    });
    host.appendChild(bulk);

    var foot = document.createElement('a');
    foot.className = 'fb-src-foot';
    foot.href = '/app/mine';
    foot.target = '_blank';
    foot.rel = 'noopener';
    foot.textContent = 'Add a list, or paste a new one →';
    host.appendChild(foot);
  }

  function showRankSources() {
    if (document.getElementById('fb-rank-sources')) { renderSources(); return; }
    if (!sources) return;
    var labels = document.querySelectorAll('span[style*="0.14em"]');
    for (var i = 0; i < labels.length; i++) {
      if (labels[i].textContent.indexOf('Board order') !== 0) continue;
      var row = labels[i].parentElement;
      if (!row || !row.parentElement) return;
      var host = document.createElement('div');
      host.id = 'fb-rank-sources';
      row.parentElement.insertBefore(host, row.nextSibling);
      renderSources();
      return;
    }
  }

  /* Re-read when the tab comes back, because the list was changed in the
   * other one. Failure is silent and leaves the injected set on screen:
   * a panel that empties itself because a fetch blipped would be worse
   * than one showing what the page was built with. */
  function refreshSources() {
    if (document.visibilityState !== 'visible' || sourcesFetching) return;
    sourcesFetching = true;
    fetch('/app/data/ranksources.json', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (fresh) {
        sourcesFetching = false;
        if (!fresh || !fresh.length) return;
        sources = fresh;
        renderSources();
      })
      .catch(function () { sourcesFetching = false; });
  }

  document.addEventListener('visibilitychange', refreshSources);
  window.addEventListener('focus', refreshSources);

  /* --- the game stack: this week's slate ranked by projected fantasy points
   * (owner, Sep 3: "show who would be the potential best games for fantasy
   * points and list them from highest to lowest and show me the expected
   * projection for highest scores").
   *
   * The ranking is arithmetic the server does (app/feeds/gamestack.py) and
   * ships in the feeds overlay under `game_stack`; this only draws it. The
   * league chips re-sort client-side because every league's figure is
   * already in the payload -- league scoring is a column here, and the
   * reader picks which column leads. Idempotent: the panel is rebuilt only
   * when the payload or the chosen league changes. */
  var stackLeague = null;

  function gsEl(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function gsPoints(v) {
    return (typeof v === 'number') ? v.toFixed(1) : '—';
  }

  function gsPlayer(p, lg) {
    var el = gsEl('span', 'fb-gs-player');
    var b = gsEl('b', '', p.name);
    el.appendChild(b);
    el.appendChild(gsEl('span', 'fb-gs-pos', p.position + ' · ' + p.team + ' · ' + gsPoints(p.points[lg])));
    if (p.injury) el.appendChild(gsEl('span', 'fb-gs-flag', p.injury));
    if (p.wire) {
      var w = gsEl('span', 'fb-gs-wire', 'Wire · ' + p.wire.time + ' · ' + p.wire.source + ' — ');
      var a = gsEl('a', '', p.wire.head);
      a.href = p.wire.link; a.target = '_blank'; a.rel = 'noopener';
      w.appendChild(a);
      el.appendChild(w);
    }
    return el;
  }

  function gsRow(g, lg, leagueName) {
    var row = gsEl('div', 'fb-gs-row');
    row.appendChild(gsEl('div', 'fb-gs-rank', String(g.rank)));
    var mid = gsEl('div', '');
    mid.appendChild(gsEl('div', 'fb-gs-game', g.away + ' @ ' + g.home));
    var line = [];
    if (g.kickoff) line.push(g.kickoff);
    if (g.tv) line.push(g.tv);
    if (g.fav) line.push(g.fav);
    if (g.total) line.push('O/U ' + g.total);
    var imp = Object.keys(g.implied || {}).map(function (c) { return c + ' ' + g.implied[c]; });
    if (imp.length) line.push('implied ' + imp.join(' · '));
    if (g.movement) line.push(g.movement);
    if (g.weather) line.push(g.weather.label || g.weather.summary);
    mid.appendChild(gsEl('div', 'fb-gs-meta', line.join(' · ')));
    var top = gsEl('div', 'fb-gs-top');
    (g.top || []).forEach(function (p) { top.appendChild(gsPlayer(p, lg)); });
    mid.appendChild(top);
    (g.out || []).forEach(function (v) {
      var nxt = v.next_points ? (' → ' + v.next + ' projected ' + gsPoints(v.next_points[lg])) : (' → ' + v.next + ' (no weekly line)');
      mid.appendChild(gsEl('div', 'fb-gs-out',
        'Out on ' + v.team + ': ' + v.starter + ' (' + v.position + ', ' + v.injury + ') · ' +
        v.vacated + " '25 touches/targets come loose" + nxt));
    });
    if (g.weather && g.weather.read) mid.appendChild(gsEl('div', 'fb-gs-meta', 'Weather read (rule): ' + g.weather.read));
    if (g.preview) mid.appendChild(gsEl('div', 'fb-gs-ai', 'AI preview: ' + g.preview));
    row.appendChild(mid);
    var pts = gsEl('div', 'fb-gs-pts');
    var side = g.points[lg] || {};
    pts.appendChild(gsEl('b', '', gsPoints(side.total)));
    pts.appendChild(gsEl('span', '', g.away + ' ' + gsPoints(side[g.away]) + ' · ' + g.home + ' ' + gsPoints(side[g.home])));
    pts.appendChild(gsEl('span', '', leagueName + ' pts'));
    row.appendChild(pts);
    return row;
  }

  function showGameStack() {
    var host = document.querySelector('[data-fb-gamestack]');
    if (!host) return;
    var stack = data && data.game_stack;
    if (!stack || !stack.games) {
      if (host.getAttribute('data-fb-sig') === 'empty') return;
      host.setAttribute('data-fb-sig', 'empty');
      host.textContent = '';
      host.appendChild(gsEl('div', 'fb-gs-head', 'Best games for fantasy points'));
      host.appendChild(gsEl('div', 'fb-gs-note',
        data ? 'No weekly forecast is stored yet. The ranking appears once the sync has this week’s ' +
               'Rotowire lines (via Sleeper) and a posted slate to score them against.'
             : 'Waiting for the live feed.'));
      return;
    }
    var lg = stackLeague || stack.default_league;
    var sig = [stack.week, stack.as_of, (stack.games || []).length, lg].join('|');
    if (host.getAttribute('data-fb-sig') === sig) return;
    host.setAttribute('data-fb-sig', sig);
    host.textContent = '';
    var names = {};
    (stack.leagues || []).forEach(function (l) { names[l.key] = l.name; });
    host.appendChild(gsEl('div', 'fb-gs-head',
      'Best games for fantasy points · Wk ' + stack.week + ' projected · ' + stack.source +
      (stack.as_of ? ' · revised ' + stack.as_of : '')));
    host.appendChild(gsEl('div', 'fb-gs-note', stack.note || ''));
    var chips = gsEl('div', 'fb-gs-chips');
    (stack.leagues || []).forEach(function (l) {
      var c = gsEl('button', 'fb-gs-chip' + (l.key === lg ? ' on' : ''), l.name);
      c.type = 'button';
      c.onclick = function () { stackLeague = l.key; host.setAttribute('data-fb-sig', ''); showGameStack(); };
      chips.appendChild(c);
    });
    host.appendChild(chips);
    var games = stack.games.slice().sort(function (a, b) {
      return (b.points[lg] || {}).total - (a.points[lg] || {}).total;
    });
    games.forEach(function (g, i) { host.appendChild(gsRow(Object.assign({}, g, { rank: i + 1 }), lg, names[lg] || lg)); });
    if (stack.uncovered && stack.uncovered.length) {
      host.appendChild(gsEl('div', 'fb-gs-foot',
        'No projected player on either side yet, so not ranked: ' + stack.uncovered.join(', ') + '.'));
    }
  }

  /* --- per-game scenarios on the FFBets tab (owner, Sep 22: "give the best
   * scenarios per game each week not just overall bets so we can look at
   * each game individually"; Sep 24, with a pick'em app's game screen as the
   * model: "still not by games … I want info on tds … I can bet on yards
   * receptions").
   *
   * Game first: a strip of the week's games in kickoff order, opening on the
   * next one to kick off. Inside a game, market tabs like the app's own --
   * Touchdowns, Passing yds, Receiving yds, Receptions, Rushing yds -- each
   * listing that game's players with Rotowire's projection (via Sleeper).
   * No book's line is available from an open source, so each row takes the
   * line the reader's app shows and says which side the projection is on:
   * arithmetic against a number they typed, never a chance we cannot back.
   * The server computes everything (app/feeds/gamestack.py `scenarios`);
   * this draws it. Typed lines live in memory only. */
  var betsGame = null;
  var betsMarket = 'game';
  var betsLines = {};
  // NFL or College (owner, Sep 26: "another section that looks at college
  // games too just like nfl -- let's keep to top 25 games"). Same panel,
  // same tabs; the college stack is composed from ESPN box scores, so its
  // numbers are season averages and its players' roles are read from what
  // they did (the box score publishes no position).
  var betsLeague = 'nfl';
  var GB_ROLE = { QB: 'Passer', RB: 'Rusher', WR: 'Receiver' };

  function gbCollege() { return betsLeague === 'college'; }

  function gbPos(p) { return gbCollege() ? (GB_ROLE[p.position] || p.position) : p.position; }

  function gbTeam(g, code) {
    var r = (g.ranks || {})[code];
    return (r ? '#' + r + ' ' : '') + code;
  }

  // Oct 8 (owner: "expand FFBets"): the rest of the markets a pick'em app
  // posts, every one a field the same weekly forecast already carries, and
  // a Matchup tab for the defense each side faces and who is hurt.
  var BET_MARKETS = [
    { id: 'game', label: 'Game' },
    { id: 'matchup', label: 'Matchup' },
    { id: 'td', label: 'Touchdowns', stat: 'td_chance' },
    { id: 'pass', label: 'Passing yds', stat: 'pass_yd' },
    { id: 'ptd', label: 'Passing TDs', stat: 'pass_td' },
    { id: 'cmp', label: 'Completions', stat: 'pass_cmp' },
    { id: 'att', label: 'Pass attempts', stat: 'pass_att' },
    { id: 'int', label: 'Interceptions', stat: 'pass_int' },
    { id: 'rec', label: 'Receiving yds', stat: 'rec_yd' },
    { id: 'recs', label: 'Receptions', stat: 'rec' },
    { id: 'rush', label: 'Rushing yds', stat: 'rush_yd' },
    { id: 'ratt', label: 'Rush attempts', stat: 'rush_att' },
    { id: 'rry', label: 'Rush + rec yds', stat: 'rush_rec_yd' }
  ];

  // Logged only for games folded since Oct 8 (gamelogs.KEEP_LATER): a game
  // without the `k` mark has no record of them, which is not a zero.
  var GB_SPARSE = { pass_cmp: 1, pass_att: 1, pass_int: 1 };

  function gbLine(label, text) {
    var row = gsEl('div', 'fb-gb-line');
    row.appendChild(gsEl('b', '', label + ' '));
    row.appendChild(gsEl('span', '', text));
    return row;
  }

  function gbShortKick(g) {
    var bits = String(g.kickoff || '').split(' · ');
    return bits.length > 1 ? bits[0].split(' ')[0] + ' ' + bits[1] : (g.kickoff || '');
  }

  // Travel and rest (owner, Oct 10: the Cowboys' three road games against
  // a side that had three at home). Measured from ESPN's schedule on the
  // server (app/feeds/travel.py); the edge is a written rule, labelled.
  function gbTravel() { return (!gbCollege() && data && data.travel) || null; }

  function gbTravelLines(g, box) {
    var t = gbTravel();
    if (!t) return;
    [g.away, g.home].forEach(function (code) {
      var r = (t.teams || {})[code];
      if (r && r.game === g.game) box.appendChild(gbLine(code + ' travel & rest:', r.line));
    });
    ((t.games || {})[g.game] || []).forEach(function (e) {
      box.appendChild(gsEl('div', 'fb-gb-impact', e));
    });
  }

  function gbSummary(g, box) {
    var sc = g.scenarios || {};
    (sc.script || []).forEach(function (t) { box.appendChild(gbLine('Script (rule):', t)); });
    if (sc.touchdowns && sc.touchdowns.length) {
      box.appendChild(gbLine('Touchdown scorers:', sc.touchdowns.map(function (p) {
        return p.name + ' (' + gbPos(p) + ' · ' + p.team + ') ' + p.tds + (gbCollege() ? ' TDs/g' : ' proj TDs') + ' ≈ ' + p.chance + '%' +
          (p.injury ? ' [' + p.injury + ']' : '');
      }).join(' · ')));
    }
    if (sc.passing && sc.passing.length) {
      box.appendChild(gbLine('Passing:', sc.passing.map(function (p) {
        return p.name + ' (' + p.team + ') ' + p.yd + ' yds · ' + p.td + ' TD' + (p.int ? ' · ' + p.int + ' INT' : '');
      }).join(' · ')));
    }
    var yards = [];
    if (sc.rushing) yards.push('rush ' + sc.rushing.name + ' (' + sc.rushing.team + ') ' + sc.rushing.yd + ' yds' +
      (sc.rushing.rush_att ? ' on ' + sc.rushing.rush_att + ' carries' : ''));
    if (sc.receiving) yards.push('rec ' + sc.receiving.name + ' (' + sc.receiving.team + ') ' + sc.receiving.yd + ' yds' +
      (sc.receiving.rec ? ' on ' + sc.receiving.rec + ' catches' : ''));
    if (yards.length) box.appendChild(gbLine('Yardage leaders:', yards.join(' · ')));
    if (sc.stack) {
      box.appendChild(gbLine('Stack:', sc.stack.qb + ' + ' + sc.stack.catchers.join(' + ') + ' (' + sc.stack.team + ')' +
        (sc.stack.bring_back ? ' · bring-back ' + sc.stack.bring_back + ' (' + sc.stack.bring_back_team + ')' : '') +
        ' — ' + sc.stack.why));
    }
    (g.out || []).forEach(function (v) {
      box.appendChild(gsEl('div', 'fb-gs-out', 'Out on ' + v.team + ': ' + v.starter + ' (' + v.position + ', ' +
        v.injury + ') → ' + v.next));
    });
    if (g.weather && g.weather.read) box.appendChild(gbLine('Weather (rule):', g.weather.summary + ' — ' + g.weather.read));
    gbTravelLines(g, box);
    if (g.preview) box.appendChild(gsEl('div', 'fb-gs-ai', 'AI preview: ' + g.preview));
  }

  function gbSub(p, market) {
    if (market === 'td') return p.td + ' proj rush + rec TDs';
    if (market === 'pass') {
      var bits = [];
      if (p.pass_td) bits.push(p.pass_td + ' TD');
      if (p.pass_cmp) bits.push(p.pass_cmp + (p.pass_att ? '/' + p.pass_att : '') + ' cmp');
      if (p.pass_int) bits.push(p.pass_int + ' INT');
      return bits.join(' · ');
    }
    if (market === 'rec') return (p.rec ? p.rec + ' catches' : '') + (p.rec_tgt ? ' on ' + p.rec_tgt + ' targets' : '');
    if (market === 'recs') return (p.rec_yd ? p.rec_yd + ' yds' : '') + (p.rec_tgt ? ' on ' + p.rec_tgt + ' targets' : '');
    if (market === 'rush') return p.rush_att ? 'on ' + p.rush_att + ' carries' : '';
    if (market === 'ptd' || market === 'cmp' || market === 'att' || market === 'int') {
      var q = [];
      if (p.pass_yd) q.push(p.pass_yd + ' yds');
      if (market !== 'cmp' && p.pass_cmp) q.push(p.pass_cmp + ' cmp');
      if (market !== 'att' && p.pass_att) q.push(p.pass_att + ' att');
      return q.join(' · ');
    }
    if (market === 'ratt') return p.rush_yd ? p.rush_yd + ' yds' : '';
    if (market === 'rry') return (p.rush_yd ? p.rush_yd + ' rush' : '') + (p.rush_yd && p.rec_yd ? ' + ' : '') +
      (p.rec_yd ? p.rec_yd + ' rec' : '');
    return '';
  }

  // The spread table the server measured from last season's box scores
  // (app/feeds/spreads.py), set each time the panel draws. Absent until the
  // whole season is folded in -- and then no percentage is printed.
  var betsSpreads = null;

  function gbNormalCdf(x) {
    // Abramowitz & Stegun 7.1.26 -- good to ~1e-7, far finer than a whole percent.
    var t = 1 / (1 + 0.3275911 * Math.abs(x) / Math.SQRT2);
    var y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t +
      0.254829592) * t * Math.exp(-x * x / 2);
    return x >= 0 ? (1 + y) / 2 : (1 - y) / 2;
  }

  // P(the stat clears the line), from a normal curve centred on the
  // projection with the measured game-to-game spread for his position.
  function gbOverChance(stat, position, proj, line) {
    var m = betsSpreads && betsSpreads.markets && betsSpreads.markets[stat];
    var cell = m && m[position];
    if (!cell || !(proj > 0)) return null;
    var sd = cell.cv * proj;
    var p = 1 - gbNormalCdf((line - proj) / sd);
    return Math.max(1, Math.min(99, Math.round(p * 100)));
  }

  function gbVerdict(proj, raw, stat, position) {
    var line = parseFloat(raw);
    if (raw === undefined || raw === null || String(raw).trim() === '' || isNaN(line)) return '';
    var diff = Math.round((proj - line) * 10) / 10;
    var over = gbOverChance(stat, position, proj, line);
    var chance = '';
    if (over !== null) {
      chance = over >= 50 ? ' · ≈' + over + '% to go over' : ' · ≈' + (100 - over) + '% to stay under';
    }
    if (diff === 0) return 'Even with your ' + line + chance;
    return (diff > 0 ? 'More · +' : 'Less · ') + diff + ' vs your ' + line + chance;
  }

  // --- the evidence under each row (owner, Sep 24: "yes" to the stats
  // behind each pick). Real games only, from Sleeper's box scores
  // (app/feeds/gamelogs.py): his log, how often he cleared the typed line,
  // and what this week's defense has allowed to his position. Every count
  // says how many games it is out of.
  var GB_STAT_WORDS = {
    pass_yd: 'passing yds', rush_yd: 'rushing yds', rec: 'catches', rec_yd: 'receiving yds',
    td: 'rush + rec TDs', pass_td: 'passing TDs', pass_cmp: 'completions', pass_att: 'pass attempts',
    pass_int: 'interceptions', rush_att: 'carries', rush_rec_yd: 'rush + rec yds'
  };

  function gbOrdinal(n) {
    var s = ['th', 'st', 'nd', 'rd'], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }

  function gbValues(p, season, key) {
    return ((p.log && p.log[season]) || [])
      .filter(function (gm) { return !GB_SPARSE[key] || gm.k; })
      .map(function (gm) { return gm[key] || 0; });
  }

  function gbRound(x) { return Math.round(x * 10) / 10; }

  function gbLogLine(p, key) {
    var now = gbValues(p, '26', key), last = gbValues(p, '25', key);
    if (!now.length && !last.length) return 'No games in the box scores yet.';
    var bits = [];
    if (key === 'td') {
      if (now.length) bits.push('TD in ' + now.filter(function (v) { return v > 0; }).length + ' of ' + now.length + " games ('26)");
      if (last.length) bits.push(last.filter(function (v) { return v > 0; }).length + ' of ' + last.length + " ('25)");
      return bits.join(' · ');
    }
    if (now.length) {
      var avg = now.reduce(function (a, b) { return a + b; }, 0) / now.length;
      bits.push("'26: " + now.slice(-5).join(' · ') + ' (avg ' + gbRound(avg) + ')');
    }
    if (last.length) {
      var avg25 = last.reduce(function (a, b) { return a + b; }, 0) / last.length;
      bits.push("'25 avg " + gbRound(avg25) + ' in ' + last.length + ' g');
    }
    return bits.join(' · ');
  }

  function gbHitLine(p, key, raw) {
    var line = parseFloat(raw);
    if (raw === undefined || raw === null || String(raw).trim() === '' || isNaN(line)) return '';
    var parts = [];
    [['26', "'26"], ['25', "'25"]].forEach(function (s) {
      var vals = gbValues(p, s[0], key);
      if (vals.length) parts.push(vals.filter(function (v) { return v > line; }).length + ' of ' + vals.length + ' (' + s[1] + ')');
    });
    return parts.length ? 'Over ' + line + ' in ' + parts.join(' · ') : '';
  }

  function gbMatchupLine(g, p, key) {
    var sc = g.scenarios || {};
    var opp = p.team === g.home ? g.away : g.home;
    var d = (sc.allowed || {})[opp];
    var cell = d && d[p.position] && d[p.position][key];
    if (!cell) return '';
    return 'vs ' + opp + ' defense: allows ' + cell[0] + ' ' + GB_STAT_WORDS[key] + '/g to ' + gbPos(p) +
      's — ' + gbPlace(cell) + ' (' + d.games + ' g)';
  }

  // [per game, rank from the most, rank from the fewest, how many share it,
  //  how many defenses have faced the position]
  function gbPlace(cell) {
    var most = cell[1], fewest = cell[2], tied = cell[3] || 1, of = cell[4];
    var near = most <= fewest ? most : fewest;
    var end = most <= fewest ? 'most' : 'fewest';
    return (near === 1 ? 'the ' + end : gbOrdinal(near) + '-' + end) +
      (tied > 1 ? ' (tied with ' + (tied - 1) + ')' : '') + ' of ' + of;
  }

  // --- the Matchup tab (owner, Oct 8: "more details on the team they are
  // facing and if any injuries could impact someone's performance"). Each
  // side's offense against the other's defense: what that defense has
  // allowed per game to each position, ranked, and every flagged starter on
  // both units. All of it is real games and Sleeper's live flags.
  var GB_DEF_VIEW = [
    ['QB', ['pass_yd']],
    ['RB', ['rush_yd', 'rec', 'td']],
    ['WR', ['rec', 'rec_yd', 'td']],
    ['TE', ['rec', 'rec_yd', 'td']]
  ];

  function gbInjuryText(r) {
    return r.name + ' (' + r.position + (r.slot > 1 ? r.slot : '') + ', ' + r.injury + ')' +
      (r.out && r.vacated ? ' — ' + r.vacated + " '25 " + r.work : '');
  }

  function gbMatchup(g, box) {
    var sc = g.scenarios || {};
    var hurt = sc.injuries || {};
    [[g.away, g.home], [g.home, g.away]].forEach(function (pair) {
      var team = pair[0], opp = pair[1];
      var block = gsEl('div', 'fb-gb-side');
      var imp = (g.implied || {})[team];
      block.appendChild(gsEl('div', 'fb-gb-sidehead', gbTeam(g, team) + ' offense vs ' + gbTeam(g, opp) + ' defense' +
        (imp !== undefined && imp !== null ? ' · implied ' + imp + ' pts' : '')));
      var d = (sc.allowed || {})[opp];
      if (d) {
        GB_DEF_VIEW.forEach(function (spec) {
          var cells = (d[spec[0]] || {});
          var bits = spec[1].filter(function (k) { return cells[k]; }).map(function (k) {
            return cells[k][0] + ' ' + GB_STAT_WORDS[k] + '/g (' + gbPlace(cells[k]) + ')';
          });
          if (bits.length) block.appendChild(gbLine(opp + ' allows to ' + gbPos({ position: spec[0] }) + 's:', bits.join(' · ')));
        });
        block.appendChild(gsEl('div', 'fb-gs-meta', 'Over ' + d.games + ' game' + (d.games === 1 ? '' : 's') +
          ' this season, from box scores.'));
      } else {
        block.appendChild(gsEl('div', 'fb-gs-note', 'No box scores against ' + opp + ' this season yet.'));
      }
      var offHurt = (hurt[team] || []).filter(function (r) { return r.side === 'offense'; });
      var defHurt = (hurt[opp] || []).filter(function (r) { return r.side === 'defense'; });
      var tr = gbTravel() && (gbTravel().teams || {})[team];
      if (tr && tr.game === g.game) block.appendChild(gbLine(team + ' travel & rest:', tr.line));
      if (!gbCollege()) {
        block.appendChild(gbLine(team + ' offense hurt:', offHurt.length ? offHurt.map(gbInjuryText).join(' · ') : 'no flagged starters'));
        block.appendChild(gbLine(opp + ' defense hurt:', defHurt.length ? defHurt.map(gbInjuryText).join(' · ') : 'no flagged starters'));
      }
      box.appendChild(block);
    });
    box.appendChild(gsEl('div', 'fb-gs-foot', gbCollege()
      ? 'Allowed per game from this season’s college box scores. College box scores carry no injury flag.'
      : 'Allowed per game from this season’s Sleeper box scores, ranked among every defense that has faced the ' +
        'position. Injuries are Sleeper’s live flags on the starters by depth chart.' +
        (gbTravel() ? ' Travel: miles between stadiums from ESPN’s schedule (pulled ' + gbTravel().as_of +
          '); a road game counts as a round trip, this week’s as the trip out.' : '')));
    var edges = (gbTravel() && (gbTravel().games || {})[g.game]) || [];
    edges.forEach(function (e) { box.insertBefore(gsEl('div', 'fb-gb-impact', e), box.lastChild); });
  }

  // --- the slip (owner, Oct 8). Picks from any game; the combined chance
  // is the legs multiplied, which assumes they are independent -- legs in
  // one game are not (a QB's yards and his receiver's move together), and
  // the slip says so rather than pretending otherwise. Memory only.
  var betsSlip = [];

  function gbSlipHas(key) { return betsSlip.some(function (l) { return l.key === key; }); }

  function gbSlipToggle(leg) {
    if (gbSlipHas(leg.key)) betsSlip = betsSlip.filter(function (l) { return l.key !== leg.key; });
    else betsSlip.push(leg);
    var host = document.querySelector('[data-fb-gamebets]');
    if (host) host.setAttribute('data-fb-sig', '');
    showGameBets();
  }

  function gbSlipButton(leg) {
    var b = gsEl('button', 'fb-gs-chip fb-gb-add' + (gbSlipHas(leg.key) ? ' on' : ''), gbSlipHas(leg.key) ? '✓ On slip' : '+ Slip');
    b.type = 'button';
    b.onclick = function () { gbSlipToggle(leg); };
    return b;
  }

  function gbFairOdds(p) {
    if (p <= 0 || p >= 1) return '';
    var o = p >= 0.5 ? -Math.round(100 * p / (1 - p)) : Math.round(100 * (1 - p) / p);
    return (o > 0 ? '+' : '') + o;
  }

  function gbSlip(host) {
    if (!betsSlip.length) return;
    var box = gsEl('div', 'fb-gb-slip');
    box.appendChild(gsEl('div', 'fb-gb-sidehead', 'Your slip · ' + betsSlip.length + ' leg' + (betsSlip.length === 1 ? '' : 's')));
    var p = 1, games = {};
    betsSlip.forEach(function (l) {
      p *= l.chance / 100;
      games[l.game] = (games[l.game] || 0) + 1;
      var row = gsEl('div', 'fb-gb-leg');
      row.appendChild(gsEl('span', '', l.label + ' · ≈' + l.chance + '%'));
      var x = gsEl('button', 'fb-gs-chip', '× ' + l.name);
      x.type = 'button';
      x.onclick = function () { gbSlipToggle(l); };
      row.appendChild(x);
      box.appendChild(row);
    });
    var pct = Math.round(p * 1000) / 10;
    box.appendChild(gbLine('All legs hit:', '≈' + pct + '% · fair odds ' + gbFairOdds(p) +
      ' — take the bet only if your app pays more than that'));
    var shared = Object.keys(games).filter(function (k) { return games[k] > 1; });
    box.appendChild(gsEl('div', 'fb-gs-foot', 'Multiplied as if every leg were independent.' +
      (shared.length ? ' Legs in the same game (' + shared.join(', ') + ') move together, so the real chance of that ' +
        'combination differs from this product — read it as rough.' : '')));
    var clear = gsEl('button', 'fb-gs-chip', 'Clear slip');
    clear.type = 'button';
    clear.onclick = function () { betsSlip = []; host.setAttribute('data-fb-sig', ''); showGameBets(); };
    box.appendChild(clear);
    host.appendChild(box);
  }

  // --- best bets across the week (owner, Oct 8). The server picks both
  // lists (gamestack.best_bets): the likeliest touchdown scorers by the
  // forecast's Poisson chance, and real roles against the defenses that
  // have allowed the most of that stat to that position. Tapping one opens
  // its game on the matching tab.
  var GB_STAT_MARKET = { pass_yd: 'pass', rush_yd: 'rush', rec_yd: 'rec', rec: 'recs' };

  function gbBest(host, stack, games) {
    var best = stack.best || {};
    var t0 = gbTravel();
    var anyEdge = t0 && games.some(function (g) { return ((t0.games || {})[g.game] || []).length; });
    if (!(best.td && best.td.length) && !(best.matchups && best.matchups.length) && !anyEdge) return;
    var box = gsEl('div', 'fb-gb-best');
    box.appendChild(gsEl('div', 'fb-gb-sidehead', 'Best bets this week · every game'));
    function open(r, market) {
      return function () {
        betsGame = r.game;
        betsMarket = market;
        host.setAttribute('data-fb-sig', '');
        showGameBets();
      };
    }
    if (best.td && best.td.length) {
      box.appendChild(gsEl('div', 'fb-gs-meta', gbCollege() ? 'Likeliest TD scorers (from TDs per game, Poisson)'
        : 'Likeliest TD scorers (forecast, Poisson)'));
      best.td.forEach(function (r) {
        var b = gsEl('button', 'fb-gb-bestrow', r.chance + '% · ' + r.name + ' (' + gbPos(r) + ' · ' + r.team + ')' +
          (r.injury ? ' [' + r.injury + ']' : '') + ' · ' + r.game.replace(' @ ', ' at '));
        b.type = 'button';
        b.onclick = open(r, 'td');
        box.appendChild(b);
      });
    }
    if (best.matchups && best.matchups.length) {
      box.appendChild(gsEl('div', 'fb-gs-meta', 'Soft matchups (defense in the top 5 for allowing it)'));
      best.matchups.forEach(function (r) {
        var b = gsEl('button', 'fb-gb-bestrow', r.name + ' (' + gbPos(r) + ' · ' + r.team + ') ' + r.proj + ' ' +
          GB_STAT_WORDS[r.stat] + ' vs ' + r.opp + ', which allows ' + r.allowed + '/g — ' + gbOrdinal(r.rank) +
          '-most of ' + r.of + (r.injury ? ' [' + r.injury + ']' : ''));
        b.type = 'button';
        b.onclick = open(r, GB_STAT_MARKET[r.stat] || 'game');
        box.appendChild(b);
      });
    }
    var t = gbTravel();
    var edged = t ? games.filter(function (g) { return ((t.games || {})[g.game] || []).length; }) : [];
    if (edged.length) {
      box.appendChild(gsEl('div', 'fb-gs-meta', 'Travel & rest edges (rule)'));
      edged.forEach(function (g) {
        var b = gsEl('button', 'fb-gb-bestrow', t.games[g.game].join(' ') + ' · ' + g.game.replace(' @ ', ' at '));
        b.type = 'button';
        b.onclick = open({ game: g.game }, 'matchup');
        box.appendChild(b);
      });
    }
    host.appendChild(box);
  }

  function gbPropRow(g, market, p) {
    var stat = market.stat;
    var row = gsEl('div', 'fb-gb-prop');
    var who = gsEl('div', 'fb-gb-who');
    who.appendChild(gsEl('b', '', p.name));
    who.appendChild(gsEl('span', 'fb-gs-pos', gbPos(p) + ' · ' + p.team));
    if (p.injury) who.appendChild(gsEl('span', 'fb-gs-flag', p.injury));
    row.appendChild(who);
    var proj = gsEl('div', 'fb-gb-proj');
    proj.appendChild(gsEl('b', '', market.id === 'td' ? p.td_chance + '%' : String(p[stat])));
    proj.appendChild(gsEl('span', '', market.id === 'td' ? 'anytime TD (Poisson)' : gbSub(p, market.id)));
    row.appendChild(proj);
    var key = market.id === 'td' ? 'td' : stat;
    var evidence = gsEl('div', 'fb-gb-stats');
    evidence.appendChild(gsEl('div', 'fb-gb-stat', gbLogLine(p, key)));
    var matchup = gbMatchupLine(g, p, key);
    if (matchup) evidence.appendChild(gsEl('div', 'fb-gb-stat', matchup));
    // The flags that touch him this week (gamestack.impact: a written rule
    // for which flags matter to whom; the men and flags are Sleeper's).
    (p.impact || []).forEach(function (t) { evidence.appendChild(gsEl('div', 'fb-gb-impact', 'Injury watch: ' + t)); });
    if (market.id === 'td') {
      if (p.td_chance) {
        row.appendChild(gbSlipButton({
          key: g.game + '|td|' + p.name, game: g.game, name: p.name,
          label: p.name + ' anytime TD', chance: p.td_chance
        }));
      }
      row.appendChild(gsEl('div', 'fb-gb-verdict', gbSub(p, 'td')));
      row.appendChild(evidence);
      return row;
    }
    var lineKey = g.game + '|' + market.id + '|' + p.name;
    var input = gsEl('input', 'fb-gb-input');
    input.type = 'text';
    input.setAttribute('inputmode', 'decimal');
    input.setAttribute('placeholder', 'Your line');
    input.setAttribute('aria-label', 'Line your app shows for ' + p.name);
    input.value = betsLines[lineKey] || '';
    var verdict = gsEl('div', 'fb-gb-verdict', gbVerdict(p[stat], input.value, stat, p.position));
    var hits = gsEl('div', 'fb-gb-stat fb-gb-hits', gbHitLine(p, key, input.value));
    // A leg needs a chance, so the slip button appears only once a typed
    // line has a measured over/under percentage behind it.
    var slot = gsEl('div', 'fb-gb-addslot');
    function legFor() {
      var line = parseFloat(input.value);
      if (isNaN(line)) return null;
      var over = gbOverChance(stat, p.position, p[stat], line);
      if (over === null) return null;
      var side = over >= 50 ? 'over' : 'under';
      return {
        key: g.game + '|' + market.id + '|' + p.name, game: g.game, name: p.name,
        label: p.name + ' ' + side + ' ' + line + ' ' + market.label.toLowerCase(),
        chance: side === 'over' ? over : 100 - over
      };
    }
    function fillSlot() {
      slot.textContent = '';
      var leg = legFor();
      if (leg || gbSlipHas(g.game + '|' + market.id + '|' + p.name)) {
        slot.appendChild(gbSlipButton(leg || { key: g.game + '|' + market.id + '|' + p.name }));
      }
    }
    fillSlot();
    input.oninput = function () {
      betsLines[lineKey] = input.value;
      verdict.textContent = gbVerdict(p[stat], input.value, stat, p.position);
      hits.textContent = gbHitLine(p, key, input.value);
      fillSlot();
    };
    row.appendChild(input);
    row.appendChild(verdict);
    row.appendChild(slot);
    evidence.insertBefore(hits, evidence.children[1] || null);
    row.appendChild(evidence);
    return row;
  }

  function gbCard(g, marketId) {
    var sc = g.scenarios || {};
    var card = gsEl('div', 'fb-gb-card');
    card.appendChild(gsEl('div', 'fb-gs-game', gbTeam(g, g.away) + ' @ ' + gbTeam(g, g.home)));
    var meta = [];
    if (g.kickoff) meta.push(g.kickoff);
    if (g.tv) meta.push(g.tv);
    if (g.fav) meta.push(g.fav);
    if (g.total) meta.push('O/U ' + g.total);
    var imp = Object.keys(g.implied || {}).map(function (c) { return c + ' ' + g.implied[c]; });
    if (imp.length) meta.push('implied ' + imp.join(' · '));
    if (g.movement) meta.push(g.movement);
    card.appendChild(gsEl('div', 'fb-gs-meta', meta.join(' · ') || 'No line posted yet'));
    var tabs = gsEl('div', 'fb-gs-chips fb-gb-tabs');
    BET_MARKETS.forEach(function (m) {
      var t = gsEl('button', 'fb-gs-chip' + (m.id === marketId ? ' on' : ''), m.label);
      t.type = 'button';
      t.onclick = function () {
        betsMarket = m.id;
        var host = document.querySelector('[data-fb-gamebets]');
        if (host) host.setAttribute('data-fb-sig', '');
        showGameBets();
      };
      tabs.appendChild(t);
    });
    card.appendChild(tabs);
    if (marketId === 'game') {
      gbSummary(g, card);
      return card;
    }
    if (marketId === 'matchup') {
      gbMatchup(g, card);
      return card;
    }
    var market = BET_MARKETS.filter(function (m) { return m.id === marketId; })[0];
    var rows = (sc.props || []).filter(function (p) { return p[market.stat] > 0; })
      .sort(function (a, b) { return b[market.stat] - a[market.stat]; });
    if (!rows.length) {
      card.appendChild(gsEl('div', 'fb-gs-note', 'No projected ' + market.label.toLowerCase() + ' in this game.'));
      return card;
    }
    rows.forEach(function (p) { card.appendChild(gbPropRow(g, market, p)); });
    var college = gbCollege();
    var source = college
      ? 'Season average per game from ESPN box scores — not a projection; no free college projection exists'
      : 'Rotowire’s projection via Sleeper';
    var spreadNote = !betsSpreads
      ? (college
        ? ' (the over/under chance appears once enough players have 3+ games this season)'
        : ' (the over/under chance appears once last season’s game-to-game spread has been measured)')
      : betsSpreads.college
        ? ', and the chance of each side: a normal curve around that average with the game-to-game spread ' +
          'measured from this season’s college box scores (players with 3+ games)'
        : ', and the chance of each side: a normal curve around the projection with the game-to-game ' +
          'spread measured from every ' + betsSpreads.season + ' regular-season box score at that position';
    card.appendChild(gsEl('div', 'fb-gs-foot', market.id === 'td'
      ? 'Chance of at least one rushing or receiving TD, read from ' +
        (college ? 'his rushing + receiving TDs per game this season' : 'the forecast’s expected TDs') +
        ' (Poisson). Passing TDs are on the Passing tab.' + (college ? '' : ' Players flagged out are left off.')
      : source + '. Type the line your app shows to see which side ' +
        (college ? 'his average' : 'the projection') + ' is on' + spreadNote + '. A model, not a guarantee.' +
        (college ? ' College box scores carry no injury flag — check your book’s status.'
          : ' Players flagged out are left off.')));
    return card;
  }

  /* --- NBA (owner, Oct 23: "add a nba section focus on points assist and
   * rebounds"). Same panel, its own markets. Every number is a real game:
   * this season's ESPN box scores and last season's ESPN game log, side by
   * side -- there is no free NBA projection, so none is shown or blended.
   * The server composes it (app/feeds/nba.py `stack`); this draws it. */
  var NBA_MARKETS = [
    { id: 'game', label: 'Game' },
    { id: 'pts', label: 'Points', idx: [0] },
    { id: 'reb', label: 'Rebounds', idx: [1] },
    { id: 'ast', label: 'Assists', idx: [2] },
    { id: 'pra', label: 'Pts + Reb + Ast', idx: [0, 1, 2] }
  ];
  var nbaMarket = 'pts';

  function nbaValue(gameRow, idx) {
    return idx.reduce(function (sum, i) { return sum + (gameRow[i] || 0); }, 0);
  }

  function nbaCount(rows, idx, line) {
    var over = 0, under = 0;
    rows.forEach(function (r) {
      var v = nbaValue(r, idx);
      if (v > line) over++;
      else if (v < line) under++;
    });
    return { over: over, under: under, n: rows.length };
  }

  function nbaHitText(p, market, text, stack) {
    var line = parseFloat(text);
    if (isNaN(line)) return '';
    var parts = [];
    [['this', stack.this_label], ['last', stack.last_label]].forEach(function (s) {
      var rows = (p.g || {})[s[0]] || [];
      if (!rows.length) return;
      var c = nbaCount(rows, market.idx, line);
      parts.push(s[1] + ': over in ' + c.over + ' of ' + c.n + (c.n - c.over - c.under ? ' (' +
        (c.n - c.over - c.under) + ' on the line)' : ''));
    });
    return parts.length ? 'Went over ' + line + ' — ' + parts.join(' · ') : 'No games stored for him yet.';
  }

  function nbaAvg(avg, market) {
    if (!avg) return null;
    return market.id === 'pra' ? avg.pra : avg[market.id];
  }

  function nbaDefenseLine(g, p, market) {
    if (market.id === 'pra') return '';
    var opp = p.team === g.away ? g.home : g.away;
    var a = (g.allowed || {})[opp];
    if (!a || !a[market.id]) return '';
    var cell = a[market.id];
    return opp + ' allows ' + cell[0] + ' ' + market.label.toLowerCase() + ' a game — ' + gbOrdinal(cell[1]) +
      '-most of ' + cell[2] + ' (' + a.n + ' game' + (a.n === 1 ? '' : 's') + ' this season)';
  }

  function nbaRecent(p, market) {
    if (!p.recent || !p.recent.length) return '';
    return 'Last ' + p.recent.length + ' (' + p.recent_season + '): ' + p.recent.map(function (r) {
      var v = market.id === 'pra' ? r[2] + r[3] + r[4] : r[{ pts: 2, reb: 3, ast: 4 }[market.id]];
      return r[0] + ' vs ' + r[1] + ' ' + (v % 1 === 0 ? String(v) : v.toFixed(1));
    }).join(' · ');
  }

  function nbaRow(g, market, p, stack) {
    var row = gsEl('div', 'fb-gb-prop');
    var who = gsEl('div', 'fb-gb-who');
    who.appendChild(gsEl('b', '', p.name));
    who.appendChild(gsEl('span', 'fb-gs-pos', (p.pos ? p.pos + ' · ' : '') + p.team));
    if (p.status) who.appendChild(gsEl('span', 'fb-gs-flag', p.status));
    row.appendChild(who);
    var now = nbaAvg(p.this, market), before = nbaAvg(p.last, market);
    var proj = gsEl('div', 'fb-gb-proj');
    proj.appendChild(gsEl('b', '', now !== null ? gsPoints(now) : (before !== null ? gsPoints(before) : '—')));
    proj.appendChild(gsEl('span', '', now !== null
      ? 'avg · ' + stack.this_label + ' · ' + p.this.n + ' g'
      : before !== null ? 'avg · ' + stack.last_label + ' · ' + p.last.n + ' g' : 'no games'));
    row.appendChild(proj);
    var lineKey = 'nba|' + g.game + '|' + market.id + '|' + p.id;
    var input = gsEl('input', 'fb-gb-input');
    input.type = 'text';
    input.setAttribute('inputmode', 'decimal');
    input.setAttribute('placeholder', 'Your line');
    input.setAttribute('aria-label', 'Line your app shows for ' + p.name);
    input.value = betsLines[lineKey] || '';
    var hits = gsEl('div', 'fb-gb-verdict', nbaHitText(p, market, input.value, stack));
    input.oninput = function () {
      betsLines[lineKey] = input.value;
      hits.textContent = nbaHitText(p, market, input.value, stack);
    };
    row.appendChild(input);
    row.appendChild(hits);
    var evidence = gsEl('div', 'fb-gb-stats');
    if (now !== null && before !== null) {
      evidence.appendChild(gsEl('div', 'fb-gb-stat', stack.last_label + ' average: ' + gsPoints(before) +
        ' over ' + p.last.n + ' games'));
    }
    var recent = nbaRecent(p, market);
    if (recent) evidence.appendChild(gsEl('div', 'fb-gb-stat', recent));
    var d = nbaDefenseLine(g, p, market);
    if (d) evidence.appendChild(gsEl('div', 'fb-gb-stat', d));
    if (p.status && p.note) evidence.appendChild(gsEl('div', 'fb-gb-impact', 'Injury report: ' + p.note));
    row.appendChild(evidence);
    return row;
  }

  function nbaSummary(g, card, stack) {
    [g.away, g.home].forEach(function (team) {
      var a = (g.allowed || {})[team];
      if (a) {
        card.appendChild(gbLine(team + ' defense allows:', ['pts', 'reb', 'ast'].map(function (k) {
          return a[k][0] + ' ' + { pts: 'pts', reb: 'reb', ast: 'ast' }[k] + ' (' + gbOrdinal(a[k][1]) + '-most)';
        }).join(' · ') + ' a game, ' + a.n + ' game' + (a.n === 1 ? '' : 's') + ' this season'));
      }
      var lead = ((g.players || {})[team] || []).filter(function (p) { return p.this; }).slice(0, 4);
      if (lead.length) {
        card.appendChild(gbLine(team + ' rotation (' + stack.this_label + '):', lead.map(function (p) {
          return p.name + ' ' + p.this.pts + '/' + p.this.reb + '/' + p.this.ast + ' in ' + p.this.min + ' min';
        }).join(' · ')));
      }
    });
    var hurt = g.injuries || [];
    card.appendChild(gbLine('Injury report:', hurt.length ? hurt.map(function (r) {
      return r.name + ' (' + r.team + ') ' + r.status + (r.note ? ' — ' + r.note : '');
    }).join(' · ') : 'nobody listed on either side'));
  }

  function nbaCard(g, stack) {
    var card = gsEl('div', 'fb-gb-card');
    card.appendChild(gsEl('div', 'fb-gs-game', g.away + ' @ ' + g.home));
    var meta = [];
    if (g.tip) meta.push(g.tip);
    if (g.tv) meta.push(g.tv);
    if (g.fav) meta.push(g.fav);
    if (g.total) meta.push('O/U ' + g.total);
    card.appendChild(gsEl('div', 'fb-gs-meta', meta.join(' · ') || 'No line posted yet'));
    var tabs = gsEl('div', 'fb-gs-chips fb-gb-tabs');
    NBA_MARKETS.forEach(function (m) {
      var t = gsEl('button', 'fb-gs-chip' + (m.id === nbaMarket ? ' on' : ''), m.label);
      t.type = 'button';
      t.onclick = function () {
        nbaMarket = m.id;
        var host = document.querySelector('[data-fb-gamebets]');
        if (host) host.setAttribute('data-fb-sig', '');
        showGameBets();
      };
      tabs.appendChild(t);
    });
    card.appendChild(tabs);
    if (nbaMarket === 'game') {
      nbaSummary(g, card, stack);
      return card;
    }
    var market = NBA_MARKETS.filter(function (m) { return m.id === nbaMarket; })[0];
    var rows = [g.away, g.home].reduce(function (all, t) { return all.concat((g.players || {})[t] || []); }, [])
      .filter(function (p) { return nbaAvg(p.this, market) !== null || nbaAvg(p.last, market) !== null; })
      .sort(function (a, b) {
        var av = nbaAvg(a.this, market), bv = nbaAvg(b.this, market);
        return (bv === null ? nbaAvg(b.last, market) : bv) - (av === null ? nbaAvg(a.last, market) : av);
      });
    if (!rows.length) {
      card.appendChild(gsEl('div', 'fb-gs-note', 'No box scores stored for either side yet.'));
      return card;
    }
    rows.forEach(function (p) { card.appendChild(nbaRow(g, market, p, stack)); });
    card.appendChild(gsEl('div', 'fb-gs-foot', 'Real averages, not a projection — no free NBA projection ' +
      'exists. ' + stack.this_label + ' from ESPN box scores, ' + stack.last_label + ' from each player’s ESPN ' +
      'game log (regular season). Type the line your app shows to count the real games that went over it; ' +
      'a game exactly on the line counts as neither. Rotation players only (15+ minutes a game). Players ESPN ' +
      'lists Out are left off' + (stack.injuries_as_of ? ' (injury report ' + stack.injuries_as_of + ')' : '') + '.'));
    return card;
  }

  function showNbaBets(host) {
    var stack = data && data.nba_stack;
    if (!stack || !stack.games || !stack.games.length) {
      var emptySig = 'empty|nba|' + !!data;
      if (host.getAttribute('data-fb-sig') === emptySig) return;
      host.setAttribute('data-fb-sig', emptySig);
      host.textContent = '';
      host.appendChild(gsEl('div', 'fb-gs-head', 'NBA FFBets'));
      host.appendChild(gbLeagueChips(host));
      host.appendChild(gsEl('div', 'fb-gs-note', !data ? 'Waiting for the live feed.'
        : 'No NBA slate is stored yet. The day’s games appear once the sync has pushed ESPN’s NBA ' +
          'scoreboard and box scores.'));
      return;
    }
    var games = stack.games.slice().sort(function (a, b) {
      return String(a.tip_iso || '').localeCompare(String(b.tip_iso || ''));
    });
    var pick = betsGame;
    if (!pick || !games.some(function (g) { return g.game === pick; })) {
      var now = Date.now();
      var next = games.filter(function (g) { return Date.parse(g.tip_iso || '') > now; })[0];
      pick = (next || games[0]).game;
    }
    var sig = ['nba', stack.day, stack.as_of, stack.injuries_as_of, games.length, pick, nbaMarket].join('|');
    if (host.getAttribute('data-fb-sig') === sig) return;
    host.setAttribute('data-fb-sig', sig);
    host.textContent = '';
    host.appendChild(gsEl('div', 'fb-gs-head', 'NBA FFBets · ' + (stack.day_label || stack.day) + ' · ' + stack.source +
      (stack.as_of ? ' · pulled ' + stack.as_of : '')));
    host.appendChild(gbLeagueChips(host));
    var chips = gsEl('div', 'fb-gs-chips fb-gb-games');
    games.forEach(function (g) {
      var c = gsEl('button', 'fb-gs-chip' + (g.game === pick ? ' on' : ''),
        g.away + ' @ ' + g.home + ' · ' + String(g.tip || '').replace(/^\w+ /, '').replace(' CT', ''));
      c.type = 'button';
      c.onclick = function () { betsGame = g.game; host.setAttribute('data-fb-sig', ''); showGameBets(); };
      chips.appendChild(c);
    });
    host.appendChild(chips);
    games.filter(function (g) { return g.game === pick; })
      .forEach(function (g) { host.appendChild(nbaCard(g, stack)); });
    if (stack.uncovered && stack.uncovered.length) {
      host.appendChild(gsEl('div', 'fb-gs-foot', 'No box scores stored for either side yet: ' +
        stack.uncovered.join(', ') + '.'));
    }
  }

  function gbLeagueChips(host) {
    var row = gsEl('div', 'fb-gs-chips fb-gb-league');
    [['nfl', 'NFL'], ['college', 'College · Top 25'], ['nba', 'NBA']].forEach(function (l) {
      var c = gsEl('button', 'fb-gs-chip' + (betsLeague === l[0] ? ' on' : ''), l[1]);
      c.type = 'button';
      c.onclick = function () {
        if (betsLeague === l[0]) return;
        betsLeague = l[0];
        betsGame = null;
        host.setAttribute('data-fb-sig', '');
        showGameBets();
      };
      row.appendChild(c);
    });
    return row;
  }

  function showGameBets() {
    var host = document.querySelector('[data-fb-gamebets]');
    if (!host) return;
    if (betsLeague === 'nba') {
      showNbaBets(host);
      return;
    }
    var college = gbCollege();
    var stack = data && (college ? data.cfb_stack : data.game_stack);
    if (!stack || !stack.games || !stack.games.length) {
      var emptySig = 'empty|' + betsLeague + '|' + !!data;
      if (host.getAttribute('data-fb-sig') === emptySig) return;
      host.setAttribute('data-fb-sig', emptySig);
      host.textContent = '';
      host.appendChild(gsEl('div', 'fb-gs-head', college ? 'College FFBets · Top 25' : 'Game by game'));
      host.appendChild(gbLeagueChips(host));
      host.appendChild(gsEl('div', 'fb-gs-note',
        !data ? 'Waiting for the live feed.'
          : college ? 'No college slate is stored yet. The week’s top-25 games appear once the sync has ' +
                      'pushed ESPN’s FBS scoreboard and box scores.'
          : 'No weekly forecast is stored yet. Each game’s props appear once the sync has this ' +
            'week’s Rotowire lines (via Sleeper) and a posted slate.'));
      return;
    }
    var games = stack.games.slice().sort(function (a, b) {
      return String(a.kickoff_iso || '').localeCompare(String(b.kickoff_iso || ''));
    });
    var pick = betsGame;
    if (!pick || !games.some(function (g) { return g.game === pick; })) {
      // Open on the next game to kick off, like the app's own game strip.
      var now = Date.now();
      var next = games.filter(function (g) { return Date.parse(g.kickoff_iso || '') > now; })[0];
      pick = (next || games[0]).game;
    }
    betsSpreads = stack.spreads || null;
    var sig = [betsLeague, stack.week, stack.as_of, games.length, pick, betsMarket, !!betsSpreads,
      (data.travel && data.travel.as_of) || '',
      betsSlip.map(function (l) { return l.key; }).join(',')].join('|');
    if (host.getAttribute('data-fb-sig') === sig) return;
    host.setAttribute('data-fb-sig', sig);
    host.textContent = '';
    host.appendChild(gsEl('div', 'fb-gs-head',
      (college ? 'College FFBets · Top 25 · Wk ' : 'Game by game · Wk ') + stack.week + ' · ' + stack.source +
      (stack.as_of ? (college ? ' · pulled ' : ' · revised ') + stack.as_of : '')));
    host.appendChild(gbLeagueChips(host));
    gbBest(host, stack, games);
    gbSlip(host);
    var chips = gsEl('div', 'fb-gs-chips fb-gb-games');
    games.forEach(function (g) {
      var c = gsEl('button', 'fb-gs-chip' + (g.game === pick ? ' on' : ''),
        gbTeam(g, g.away) + ' @ ' + gbTeam(g, g.home) + ' · ' + gbShortKick(g));
      c.type = 'button';
      c.onclick = function () { betsGame = g.game; host.setAttribute('data-fb-sig', ''); showGameBets(); };
      chips.appendChild(c);
    });
    host.appendChild(chips);
    games.filter(function (g) { return g.game === pick; })
      .forEach(function (g) { host.appendChild(gbCard(g, betsMarket)); });
    if (stack.uncovered && stack.uncovered.length) {
      host.appendChild(gsEl('div', 'fb-gs-foot',
        (college ? 'No box scores stored for either side yet: ' : 'No projected player on either side yet: ') +
        stack.uncovered.join(', ') + '.'));
    }
  }

  /* --- weekly stars: the week's projected leaders by position (owner, Sep 3:
   * "players with best value for the week -- this helps drive who I play").
   * Same contract as the game stack: the server computes, this draws, the
   * chips re-sort client-side. Defenders show projected tackles beside the
   * points, because tackles are the IDP week. */
  var starsLeague = null;
  var starsPos = null;

  function starRow(p, lg) {
    var row = gsEl('div', 'fb-gs-row fb-ws-row');
    var pts = p.points[lg];
    var left = gsEl('div', 'fb-gs-pts fb-ws-pts');
    left.appendChild(gsEl('b', '', pts === null || pts === undefined ? '—' : gsPoints(pts)));
    left.appendChild(gsEl('span', '', p.tackles !== null && p.tackles !== undefined ? p.tackles + ' tkl' : 'pts'));
    row.appendChild(left);
    var mid = gsEl('div', '');
    var nameLine = gsEl('div', 'fb-gs-game');
    nameLine.appendChild(gsEl('span', '', p.name));
    nameLine.appendChild(gsEl('span', 'fb-gs-pos', p.slot + ' · ' + p.team));
    if (p.injury) nameLine.appendChild(gsEl('span', 'fb-gs-flag', p.injury));
    if (p.practice) nameLine.appendChild(gsEl('span', 'fb-gs-flag', 'practice: ' + p.practice));
    mid.appendChild(nameLine);
    var meta = [];
    if (p.solo !== null && p.solo !== undefined) meta.push(p.solo + ' solo of ' + p.tackles + ' projected tackles');
    if (p.depth) meta.push('depth ' + p.depth);
    if (meta.length) mid.appendChild(gsEl('div', 'fb-gs-meta', meta.join(' · ')));
    if (p.wire) {
      var w = gsEl('div', 'fb-gs-wire', 'Wire · ' + p.wire.time + ' · ' + p.wire.source + ' — ');
      var a = gsEl('a', '', p.wire.head);
      a.href = p.wire.link; a.target = '_blank'; a.rel = 'noopener';
      w.appendChild(a);
      mid.appendChild(w);
    }
    row.appendChild(mid);
    row.appendChild(gsEl('div', ''));
    return row;
  }

  function showWeeklyStars() {
    var host = document.querySelector('[data-fb-weeklystars]');
    if (!host) return;
    var stars = data && data.weekly_stars;
    if (!stars || !stars.groups) {
      if (host.getAttribute('data-fb-sig') === 'empty') return;
      host.setAttribute('data-fb-sig', 'empty');
      host.textContent = '';
      host.appendChild(gsEl('div', 'fb-gs-head', 'Weekly stars'));
      host.appendChild(gsEl('div', 'fb-gs-note',
        data ? 'No weekly forecast is stored yet. The week’s projected leaders appear once the sync ' +
               'has this week’s Rotowire lines (via Sleeper).'
             : 'Waiting for the live feed.'));
      return;
    }
    var lg = starsLeague || stars.default_league;
    var pos = (starsPos && stars.groups[starsPos]) ? starsPos : (stars.positions[0] || '');
    var sig = [stars.week, stars.as_of, lg, pos].join('|');
    if (host.getAttribute('data-fb-sig') === sig) return;
    host.setAttribute('data-fb-sig', sig);
    host.textContent = '';
    var names = {};
    (stars.leagues || []).forEach(function (l) { names[l.key] = l.name; });
    host.appendChild(gsEl('div', 'fb-gs-head',
      'Weekly stars · Wk ' + stars.week + ' projected · ' + stars.source +
      (stars.as_of ? ' · revised ' + stars.as_of : '')));
    host.appendChild(gsEl('div', 'fb-gs-note', stars.note || ''));
    var chips = gsEl('div', 'fb-gs-chips');
    (stars.positions || []).forEach(function (p) {
      var c = gsEl('button', 'fb-gs-chip' + (p === pos ? ' on' : ''), p);
      c.type = 'button';
      c.onclick = function () { starsPos = p; host.setAttribute('data-fb-sig', ''); showWeeklyStars(); };
      chips.appendChild(c);
    });
    host.appendChild(chips);
    var lchips = gsEl('div', 'fb-gs-chips');
    (stars.leagues || []).forEach(function (l) {
      var c = gsEl('button', 'fb-gs-chip' + (l.key === lg ? ' on' : ''), l.name);
      c.type = 'button';
      c.onclick = function () { starsLeague = l.key; host.setAttribute('data-fb-sig', ''); showWeeklyStars(); };
      lchips.appendChild(c);
    });
    host.appendChild(lchips);
    var rows = (stars.groups[pos] || []).slice().sort(function (a, b) {
      var av = a.points[lg], bv = b.points[lg];
      return (bv === null || bv === undefined ? -1 : bv) - (av === null || av === undefined ? -1 : av);
    });
    rows.forEach(function (p) { host.appendChild(starRow(p, lg)); });
    host.appendChild(gsEl('div', 'fb-gs-foot', (names[lg] || lg) + ' scoring · ' + pos +
      (pos === 'LB' || pos === 'DB' || pos === 'DL' ? ' · tackles = solo + assisted, projected' : '')));
  }

  function decorate() {
    applyTeamTheme();
    offerTeamPicker();
    linkDraftTools();
    showRankSources();
    showSleepers();
    showGameStack();
    showGameBets();
    showWeeklyStars();
    if (!data) return;
    badgeNews();
    stampInjury();
  }

  new MutationObserver(schedule).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
