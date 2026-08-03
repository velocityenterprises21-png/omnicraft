/* OMNICRAFT — the overview dashboard: credit balance, usage stats,
   module readiness and recent activity. Populates #view-overview. */
(function (global) {
  'use strict';

  var Dashboard = {
    /* Called by App after capabilities load and whenever the overview shows. */
    render: function () {
      Dashboard.stats();
      Dashboard.modules();
      /* Recent job activity is owned by the Jobs module, which paints
         #overviewJobs. Nudge it so the card is current. */
      if (global.Jobs) Jobs.render();
    },

    stats: function () {
      var host = document.getElementById('overviewStats');
      if (!host || !Auth.user) return;
      var caps = Auth.capabilities;
      var modules = (caps && caps.modules) || {};
      var total = Object.keys(modules).length;
      var ready = Object.values(modules).filter(function (m) { return m.ready; }).length;

      host.innerHTML =
        '<div class="stat"><div class="stat__label">Credits</div>' +
          '<div class="stat__value">' + Auth.user.credits_balance.toLocaleString() + '</div></div>' +
        '<div class="stat"><div class="stat__label">Plan</div>' +
          '<div class="stat__value" style="font-size:18px">' + UI.escape(Auth.user.tier) + '</div></div>' +
        '<div class="stat"><div class="stat__label">Storage used</div>' +
          '<div class="stat__value" style="font-size:18px">' + UI.bytes(Auth.user.storage_used) + '</div></div>' +
        '<div class="stat"><div class="stat__label">Modules ready</div>' +
          '<div class="stat__value">' + (total ? ready + '/' + total : '—') + '</div></div>';
    },

    modules: function () {
      var host = document.getElementById('moduleStatus');
      if (!host) return;
      var caps = Auth.capabilities;
      if (!caps || !caps.modules) {
        host.innerHTML = '<p class="muted small">Checking module status…</p>';
        return;
      }
      host.innerHTML = Object.keys(caps.modules).map(function (key) {
        var m = caps.modules[key];
        var bg = m.ready ? 'rgba(70,217,154,.15)' : 'rgba(255,196,107,.15)';
        var fg = m.ready ? 'var(--ok)' : 'var(--warn)';
        return '<div class="file">' +
          '<div class="file__kind" style="background:' + bg + ';color:' + fg + '">' +
            (m.ready ? 'ok' : 'set') + '</div>' +
          '<div><div class="file__name">' + UI.escape(key) + '</div>' +
          '<div class="file__meta">' +
            UI.escape(m.note || (m.provider || m.engine || m.backend || 'Ready')) +
          '</div></div><div></div></div>';
      }).join('');
    }
  };

  global.Dashboard = Dashboard;
})(window);
