/* Operator console. Only rendered for admin accounts. */
(function (global) {
  'use strict';

  var Admin = {
    mount: async function (host) {
      host.innerHTML = '<div class="card"><span class="spinner"></span> Loading…</div>';
      try {
        var stats = await API.get('/api/admin/stats');
        var revenue = await API.get('/api/admin/revenue');
        var users = await API.get('/api/admin/users?limit=50');
        Admin.paint(host, stats, revenue, users);
      } catch (error) {
        host.innerHTML = UI.notice(error.message || 'Admin data is unavailable.', 'warn');
      }
    },

    paint: function (host, stats, revenue, users) {
      host.innerHTML =
        '<div class="grid cols-4 mb">' +
          Admin.stat('Accounts', stats.users.total) +
          Admin.stat('Paying', stats.users.paying) +
          Admin.stat('MRR', UI.money(revenue.mrr)) +
          Admin.stat('ARR', UI.money(revenue.arr)) +
        '</div>' +
        '<div class="grid cols-4 mb">' +
          Admin.stat('Jobs run', stats.jobs.total) +
          Admin.stat('Failure rate', stats.jobs.failure_rate + '%') +
          Admin.stat('Storage', UI.bytes(stats.storage_bytes)) +
          Admin.stat('Live sockets', stats.live_connections) +
        '</div>' +
        '<div class="card">' +
          '<h2 class="card__title">Revenue by tier</h2>' +
          '<p class="card__hint">' + UI.escape(revenue.note) + '</p>' +
          '<div class="table-wrap"><table class="table"><thead><tr>' +
            '<th>Tier</th><th>Cycle</th><th>Subscribers</th><th>MRR</th></tr></thead><tbody>' +
            (revenue.breakdown.length ? revenue.breakdown.map(function (r) {
              return '<tr><td>' + UI.escape(r.tier) + '</td><td>' + UI.escape(r.interval) + '</td>' +
                '<td class="num">' + r.subscribers + '</td><td class="num">' + UI.money(r.mrr) + '</td></tr>';
            }).join('') : '<tr><td colspan="4" class="muted">No paid subscriptions yet.</td></tr>') +
          '</tbody></table></div>' +
        '</div>' +
        '<div class="card">' +
          '<h2 class="card__title">Usage by module</h2>' +
          '<div class="table-wrap"><table class="table"><thead><tr><th>Module</th><th>Runs</th></tr></thead><tbody>' +
            (Object.keys(stats.usage_by_feature).length
              ? Object.keys(stats.usage_by_feature).map(function (k) {
                  return '<tr><td>' + UI.escape(k) + '</td><td class="num">' +
                         stats.usage_by_feature[k] + '</td></tr>';
                }).join('')
              : '<tr><td colspan="2" class="muted">Nothing has run yet.</td></tr>') +
          '</tbody></table></div>' +
        '</div>' +
        '<div class="card">' +
          '<h2 class="card__title">Accounts</h2>' +
          '<div class="field"><input class="input" id="adSearch" placeholder="Search by email or username"></div>' +
          '<div class="table-wrap" id="adUsers">' + Admin.userTable(users.users) + '</div>' +
        '</div>';

      var search = document.getElementById('adSearch');
      var timer;
      search.oninput = function () {
        clearTimeout(timer);
        timer = setTimeout(async function () {
          var found = await API.get('/api/admin/users?limit=50&q=' + encodeURIComponent(search.value));
          document.getElementById('adUsers').innerHTML = Admin.userTable(found.users);
        }, 300);
      };
    },

    stat: function (label, value) {
      return '<div class="stat"><div class="stat__label">' + label +
             '</div><div class="stat__value">' + value + '</div></div>';
    },

    userTable: function (users) {
      if (!users.length) return '<p class="muted small">No matching accounts.</p>';
      return '<table class="table"><thead><tr>' +
        '<th>Account</th><th>Tier</th><th>Credits</th><th>Storage</th><th>Joined</th><th></th>' +
        '</tr></thead><tbody>' + users.map(function (u) {
          return '<tr><td>' + UI.escape(u.username) + '<div class="file__meta">' +
              UI.escape(u.email) + '</div></td>' +
            '<td>' + UI.escape(u.tier) + '</td>' +
            '<td class="num">' + u.credits_balance.toLocaleString() + '</td>' +
            '<td class="num">' + UI.bytes(u.storage_used) + '</td>' +
            '<td class="num">' + UI.date(u.created_at) + '</td>' +
            '<td><button class="btn btn--ghost btn--sm" data-grant="' + u.id + '">Add credits</button></td></tr>';
        }).join('') + '</tbody></table>';
    }
  };

  document.addEventListener('click', async function (e) {
    var button = e.target.closest('[data-grant]');
    if (!button) return;
    var amount = prompt('How many credits should this account receive? Use a negative number to remove.');
    if (amount === null || amount === '') return;
    try {
      var res = await API.post('/api/admin/users/' + button.getAttribute('data-grant') +
                               '/credits?amount=' + encodeURIComponent(amount) +
                               '&reason=' + encodeURIComponent('Operator adjustment'));
      UI.ok('Balance updated', 'New balance: ' + res.balance.toLocaleString());
    } catch (error) { UI.fail(error, 'Could not adjust that balance.'); }
  });

  global.Admin = Admin;
})(window);
