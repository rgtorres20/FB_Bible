/* Mobile menu drawer.
 *
 * Injected at serve time next to mobile.css (index.html on disk stays
 * pristine -- see the no-fork note in docs/HOSTING.md). Adds a ☰ button and
 * a backdrop; mobile.css turns the aside into a slide-in drawer so the phone
 * gets the SAME sidebar as the laptop, not a substitute for it.
 *
 * The page hydrates asynchronously (support.js renders into <x-dc>), so the
 * aside does not exist at DOMContentLoaded. Poll a few seconds, then give up
 * quietly -- a missing menu button degrades to the desktop layout, which
 * still scrolls.
 */
(function () {
  var tries = 0;

  function init() {
    var aside = document.querySelector('aside');
    if (!aside) {
      if (tries++ < 600) requestAnimationFrame(init);
      return;
    }
    if (document.getElementById('fb-menu-btn')) return;

    var btn = document.createElement('button');
    btn.id = 'fb-menu-btn';
    btn.setAttribute('aria-label', 'Open menu');
    btn.textContent = '☰';

    var backdrop = document.createElement('div');
    backdrop.id = 'fb-backdrop';

    function close() {
      document.body.classList.remove('fb-menu-open');
    }

    btn.addEventListener('click', function () {
      document.body.classList.toggle('fb-menu-open');
    });
    backdrop.addEventListener('click', close);

    // Picking a tab should land you on it, not leave the drawer covering it.
    // Only nav buttons close it -- SYNC NOW and the theme picker stay usable
    // inside the open drawer.
    aside.addEventListener('click', function (event) {
      if (event.target.closest('nav button')) close();
    });

    document.body.appendChild(backdrop);
    document.body.appendChild(btn);
  }

  init();
})();
