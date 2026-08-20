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
      } else {
        stamp.textContent = 'No wire mention in the last 21 days';
      }
      row.appendChild(stamp);
    }
  }

  /* The Draft analyzer gains a link to the mock draft room (owner request,
   * Aug 20: simulate the draft from their exact slot). Anchored on the
   * screen's own "My team" header so it only ever renders there; opens in
   * a new tab because in-shell navigation strands the PWA (see above). */
  function linkMockRoom() {
    if (document.getElementById('fb-mock-link')) return;
    var headers = document.querySelectorAll('div[style*="0.14em"]');
    for (var i = 0; i < headers.length; i++) {
      if (headers[i].textContent.indexOf('My team') !== 0) continue;
      var a = document.createElement('a');
      a.id = 'fb-mock-link';
      a.href = '/app/mock';
      a.target = '_blank';
      a.rel = 'noopener';
      a.textContent = 'Mock draft room — simulate from your slot →';
      headers[i].parentElement.insertBefore(a, headers[i]);
      return;
    }
  }

  function decorate() {
    linkMockRoom();
    if (!data) return;
    badgeNews();
    stampInjury();
  }

  new MutationObserver(schedule).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
