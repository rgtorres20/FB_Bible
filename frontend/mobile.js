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

  fetch('data/feeds.json')
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (f) { if (f) { data = f; schedule(); } })
    .catch(function () {});

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
      var info = wire[names[j].textContent.trim()];
      var stamp = document.createElement('div');
      stamp.className = 'fb-wire-stamp';
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
          stamp.textContent = text;
        }
      } else if (data && ('injury_wire' in data)) {
        /* The negative is only a measurement when the server actually
         * checked: injury_wire present-but-empty means "checked, quiet",
         * while an absent key means no poll has run -- claiming 21
         * quiet days off the bundled file would be an unmeasured
         * measurement. */
        stamp.textContent = 'No wire mention in the last 21 days';
      } else {
        stamp.textContent = 'Wire check pending — no poll yet';
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
    ['fb-scoring-link', '/app/scoring', 'Scoring board — who scores most in each league →']
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

  function decorate() {
    applyTeamTheme();
    offerTeamPicker();
    linkDraftTools();
    showRankSources();
    showSleepers();
    if (!data) return;
    badgeNews();
    stampInjury();
  }

  new MutationObserver(schedule).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
