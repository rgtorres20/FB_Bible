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
    meta.textContent = bits.join(' · ');
    var state = document.createElement('span');
    state.className = 'fb-src-state';
    state.textContent = s.active ? 'in the average' : 'off';
    row.appendChild(name);
    row.appendChild(meta);
    row.appendChild(state);
    return row;
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

    var foot = document.createElement('a');
    foot.className = 'fb-src-foot';
    foot.href = '/app/mine';
    foot.target = '_blank';
    foot.rel = 'noopener';
    foot.textContent = 'Add, switch off or remove a list →';
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
    if (!data) return;
    badgeNews();
    stampInjury();
  }

  new MutationObserver(schedule).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
