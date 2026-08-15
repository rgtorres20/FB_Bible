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
