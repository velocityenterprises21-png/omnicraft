/* OMNICRAFT — public landing page: pricing toggle, FAQ, and the hand-off
   into the sign-in gate. Static marketing data so it renders with no API. */
(function (global) {
  'use strict';

  var PLANS = [
    { name: 'free',       label: 'Free',       m: 0,      y: 0,       featured: false,
      lines: ['5 starter credits (one-time)', '1 GB storage', 'Up to 1 min video', '480p export', 'Watermarked'] },
    { name: 'starter',    label: 'Starter',    m: 9.99,   y: 95.88,   featured: false,
      lines: ['100 credits / month', '10 GB storage', 'Up to 10 min video', '720p export', 'No watermark'] },
    { name: 'pro',        label: 'Pro',        m: 24.99,  y: 239.88,  featured: true,
      lines: ['350 credits / month', '50 GB storage', 'Up to 30 min video', '1080p export', 'Priority queue'] },
    { name: 'business',   label: 'Business',   m: 59.99,  y: 575.88,  featured: false,
      lines: ['1,200 credits / month', '200 GB storage', 'Up to 60 min video', '4K export', 'API access'] },
    { name: 'enterprise', label: 'Enterprise', m: 149.99, y: 1439.88, featured: false,
      lines: ['4,000 credits / month', '1 TB storage', 'Unlimited length', '8K export', 'White-label'] },
    { name: 'ultimate',   label: 'Ultimate',   m: 299.99, y: 2879.88, featured: false,
      lines: ['12,000 credits / month', '5 TB storage', 'Unlimited length', '8K+ export', 'Dedicated pool + SLA'] }
  ];

  var PACKS = [
    { credits: 50, price: 4.99 }, { credits: 100, price: 8.99 }, { credits: 250, price: 19.99 },
    { credits: 500, price: 34.99 }, { credits: 1000, price: 59.99 }, { credits: 5000, price: 249.99 },
    { credits: 10000, price: 449.99 }
  ];

  var money = function (n) { return '$' + Number(n).toFixed(2).replace(/\.00$/, ''); };

  var Landing = {
    yearly: false,

    init: function () {
      var el = document.getElementById('landing');
      if (!el) return;

      Landing.renderPlans();
      Landing.renderPacks();

      var toggle = document.getElementById('lpToggle');
      if (toggle) {
        toggle.onclick = function () {
          Landing.yearly = !Landing.yearly;
          toggle.setAttribute('aria-pressed', String(Landing.yearly));
          document.getElementById('lpLblM').classList.toggle('on', !Landing.yearly);
          document.getElementById('lpLblY').classList.toggle('on', Landing.yearly);
          Landing.renderPlans();
        };
      }

      /* FAQ accordion */
      el.querySelectorAll('.lp-q__head').forEach(function (head) {
        head.onclick = function () { head.parentNode.classList.toggle('open'); };
      });

      /* Any CTA that opens the gate */
      el.querySelectorAll('[data-open]').forEach(function (b) {
        b.onclick = function () { Landing.openGate(b.getAttribute('data-open')); };
      });

      /* Back link inside the gate returns to the landing page */
      var back = document.getElementById('gateBack');
      if (back) back.onclick = Landing.show;

      /* Smooth-scroll the in-page nav links */
      el.querySelectorAll('a[href^="#lp-"]').forEach(function (a) {
        a.onclick = function (e) {
          var target = document.getElementById(a.getAttribute('href').slice(1));
          if (target) { e.preventDefault(); target.scrollIntoView({ behavior: 'smooth' }); }
        };
      });

      /* Deep link: /?open=create or #get-started jumps straight to sign-up */
      var params = new URLSearchParams(location.search);
      if (params.get('open') === 'create' || location.hash === '#get-started') {
        Landing.openGate('create');
      }
    },

    renderPlans: function () {
      var host = document.getElementById('lpPlans');
      if (!host) return;
      host.innerHTML = PLANS.map(function (p) {
        var perMonth = Landing.yearly && p.y ? p.y / 12 : p.m;
        var saving = p.m * 12 - p.y;
        return '<div class="plan' + (p.featured ? ' plan--featured' : '') + '">' +
          (p.featured ? '<span class="plan__tag">Most picked</span>' : '') +
          '<div class="plan__name">' + p.label + '</div>' +
          '<div class="plan__price">' + (p.m === 0 ? 'Free' : money(perMonth)) + '</div>' +
          '<div class="plan__cycle">' + (p.m === 0
            ? 'No card needed'
            : (Landing.yearly ? 'per month, billed yearly' : 'per month')) + '</div>' +
          (Landing.yearly && saving > 0 ? '<div class="plan__save">Saves ' + money(saving) + ' a year</div>' : '') +
          '<ul class="plan__list">' + p.lines.map(function (l) { return '<li>' + l + '</li>'; }).join('') + '</ul>' +
          '<div class="plan__cta"><button class="btn btn--block' + (p.featured ? '' : ' btn--ghost') +
            '" data-open="' + (p.m === 0 ? 'create' : 'create') + '">' +
            (p.m === 0 ? 'Start free' : 'Choose ' + p.label) + '</button></div>' +
        '</div>';
      }).join('');
      host.querySelectorAll('[data-open]').forEach(function (b) {
        b.onclick = function () { Landing.openGate(b.getAttribute('data-open')); };
      });
    },

    renderPacks: function () {
      var host = document.getElementById('lpPacks');
      if (!host) return;
      host.innerHTML = PACKS.map(function (p) {
        return '<div class="pack">' +
          '<div class="pack__credits">' + p.credits.toLocaleString() + '</div>' +
          '<div class="pack__price">' + money(p.price) + '</div>' +
          '<div class="pack__unit">' + (p.price / p.credits).toFixed(3) + ' each</div>' +
        '</div>';
      }).join('');
    },

    openGate: function (tab) {
      document.getElementById('landing').hidden = true;
      document.getElementById('gate').hidden = false;
      var which = tab === 'create' ? 'tabCreate' : 'tabSignIn';
      var btn = document.getElementById(which);
      if (btn) btn.click();
      window.scrollTo(0, 0);
    },

    show: function () {
      document.getElementById('gate').hidden = true;
      var el = document.getElementById('landing');
      if (el) { el.hidden = false; el.scrollTop = 0; }
    }
  };

  global.Landing = Landing;
  document.addEventListener('DOMContentLoaded', function () { Landing.init(); });
})(window);
