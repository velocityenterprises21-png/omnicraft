/* Channel 11 — plans, credit packs and billing. */
(function (global) {
  'use strict';

  var Pricing = {
    data: null,
    yearly: false,

    mount: async function (host) {
      host.innerHTML = '<div class="card"><span class="spinner"></span> Loading plans…</div>';
      try {
        Pricing.data = await API.get('/api/payments/plans');
      } catch (error) {
        host.innerHTML = UI.notice('Could not load the plan catalog. ' + (error.message || ''), 'warn');
        return;
      }
      Pricing.paint(host);
    },

    paint: function (host) {
      var data = Pricing.data;
      var plans = data.plans || [];

      host.innerHTML =
        (data.billing_enabled ? '' : UI.notice(
          'Stripe isn\'t connected, so checkout is disabled. Add STRIPE_SECRET_KEY to sell plans. ' +
          'Everything else on the platform still runs.', 'warn')) +
        '<div class="toggle-row">' +
          '<span class="toggle-label' + (Pricing.yearly ? '' : ' on') + '" id="lblMonthly">Monthly</span>' +
          '<button class="toggle" id="cycleToggle" aria-pressed="' + Pricing.yearly + '" aria-label="Billing cycle">' +
            '<span class="toggle__knob"></span></button>' +
          '<span class="toggle-label' + (Pricing.yearly ? ' on' : '') + '" id="lblYearly">Yearly</span>' +
          '<span class="save-chip">Save 20%</span>' +
        '</div>' +
        '<div class="plans mb">' + plans.map(Pricing.planCard).join('') + '</div>' +
        Pricing.comparison(plans) +
        Pricing.packs(data.credit_packages || []) +
        Pricing.costs(data.credit_costs || {}) +
        '<div class="card">' +
          '<h2 class="card__title">Manage billing</h2>' +
          '<p class="card__hint">Update your card, download invoices, or cancel. Cancelling keeps your plan until the period ends.</p>' +
          '<div class="btn-row">' +
            '<button class="btn btn--ghost" id="prPortal">Open the billing portal</button>' +
            '<button class="btn btn--danger" id="prCancel">Cancel my plan</button>' +
          '</div>' +
        '</div>';

      document.getElementById('cycleToggle').onclick = function () {
        Pricing.yearly = !Pricing.yearly;
        Pricing.paint(host);
      };
      document.getElementById('prPortal').onclick = Pricing.portal;
      document.getElementById('prCancel').onclick = Pricing.cancel;

      host.querySelectorAll('[data-plan]').forEach(function (b) {
        b.onclick = function () { Pricing.checkout({ plan: b.getAttribute('data-plan'),
                                                     interval: Pricing.yearly ? 'yearly' : 'monthly' }); };
      });
      host.querySelectorAll('[data-pack]').forEach(function (b) {
        b.onclick = function () { Pricing.checkout({ credit_pack: b.getAttribute('data-pack') }); };
      });
    },

    planCard: function (plan) {
      var current = Auth.user && Auth.user.tier === plan.name;
      var yearly = Pricing.yearly;
      var price = yearly ? plan.price_yearly / 12 : plan.price_monthly;
      var saving = plan.price_monthly * 12 - plan.price_yearly;

      return '<div class="plan' + (plan.name === 'pro' ? ' plan--featured' : '') + '">' +
        (plan.name === 'pro' ? '<span class="plan__tag">Most picked</span>' : '') +
        '<div class="plan__name">' + UI.escape(plan.display_name) + '</div>' +
        '<div class="plan__price">' + (plan.price_monthly === 0 ? 'Free' : UI.money(price)) + '</div>' +
        '<div class="plan__cycle">' + (plan.price_monthly === 0
          ? 'No card needed'
          : (yearly ? 'per month, billed yearly' : 'per month')) + '</div>' +
        (yearly && saving > 0 ? '<div class="plan__save">Saves ' + UI.money(saving) + ' a year</div>' : '') +
        '<ul class="plan__list">' + (plan.features || []).map(function (f) {
          return '<li>' + UI.escape(f) + '</li>';
        }).join('') + '</ul>' +
        '<div class="plan__cta">' +
          (current
            ? '<button class="btn btn--quiet btn--block" disabled>Your current plan</button>'
            : (plan.price_monthly === 0
              ? '<button class="btn btn--ghost btn--block" disabled>Starting tier</button>'
              : '<button class="btn btn--block" data-plan="' + plan.name + '"' +
                (Pricing.data.billing_enabled ? '' : ' disabled') + '>Choose ' +
                UI.escape(plan.display_name) + '</button>')) +
        '</div></div>';
    },

    comparison: function (plans) {
      var rows = [
        ['Credits included', function (p) { return p.credits_included.toLocaleString(); }],
        ['Storage', function (p) { return UI.bytes(p.storage_limit); }],
        ['Max video length', function (p) {
          return p.max_video_length ? Math.round(p.max_video_length / 60) + ' min' : 'Unlimited';
        }],
        ['Export quality', function (p) { return p.export_quality; }],
        ['Priority queue', function (p) { return p.priority_queue ? 'Yes' : '—'; }],
        ['API access', function (p) { return p.api_access ? 'Yes' : '—'; }],
        ['White label', function (p) { return p.white_label ? 'Yes' : '—'; }],
        ['Watermark', function (p) { return p.watermark ? 'On exports' : 'None'; }]
      ];
      return '<div class="card"><h2 class="card__title">Side by side</h2>' +
        '<div class="table-wrap"><table class="table"><thead><tr><th></th>' +
        plans.map(function (p) { return '<th>' + UI.escape(p.display_name) + '</th>'; }).join('') +
        '</tr></thead><tbody>' +
        rows.map(function (row) {
          return '<tr><td>' + row[0] + '</td>' +
            plans.map(function (p) { return '<td class="num">' + UI.escape(row[1](p)) + '</td>'; }).join('') +
          '</tr>';
        }).join('') +
        '</tbody></table></div></div>';
    },

    packs: function (packs) {
      return '<div class="card"><h2 class="card__title">Extra credits</h2>' +
        '<p class="card__hint">One-time top ups. They never expire and stack on top of your plan allowance.</p>' +
        '<div class="packs">' + packs.map(function (p) {
          return '<button class="pack" data-pack="' + p.code + '"' +
            (Pricing.data.billing_enabled ? '' : ' disabled') + '>' +
            '<div class="pack__credits">' + p.credits.toLocaleString() + '</div>' +
            '<div class="pack__price">' + UI.money(p.price_usd) + '</div>' +
            '<div class="pack__unit">' + (p.price_usd / p.credits).toFixed(3) + ' each</div>' +
          '</button>';
        }).join('') + '</div></div>';
    },

    costs: function (costs) {
      var labels = {
        'download.short': 'Download, under 5 minutes',
        'download.long': 'Download, 5 to 30 minutes',
        'download.hires': 'Download, 4K or 8K source',
        'tts.per_minute': 'Voiceover, per minute',
        'narration': 'Narration mix',
        'subtitles.extract': 'Subtitle extraction',
        'subtitles.translate': 'Subtitle translation',
        'storyline': 'Storyline rewrite',
        'rights.scan': 'Rights screening',
        'rights.remediate': 'Rights clearance',
        'research.basic': 'Research, basic',
        'research.deep': 'Research, deep',
        'priority_surcharge': 'Priority processing surcharge'
      };
      var video = (Pricing.data.video_credit_table || [
        { minutes: 1, quality: '720p', credits: 15 },
        { minutes: 5, quality: '1080p', credits: 50 },
        { minutes: 20, quality: '4K', credits: 200 },
        { minutes: 60, quality: '4K', credits: 600 },
        { minutes: 60, quality: '8K', credits: 900 }
      ]);

      return '<div class="card"><h2 class="card__title">What things cost</h2>' +
        '<div class="table-wrap"><table class="table"><thead><tr><th>Action</th><th>Credits</th></tr></thead><tbody>' +
        Object.keys(labels).filter(function (k) { return costs[k] !== undefined; }).map(function (k) {
          return '<tr><td>' + labels[k] + '</td><td class="num">' + costs[k] + '</td></tr>';
        }).join('') +
        video.map(function (v) {
          return '<tr><td>AI video, ' + v.minutes + ' min at ' + v.quality + '</td>' +
                 '<td class="num">' + v.credits + '</td></tr>';
        }).join('') +
        '</tbody></table></div></div>';
    },

    checkout: async function (body) {
      try {
        var session = await API.post('/api/payments/create-checkout', body);
        if (session && session.url) location.href = session.url;
      } catch (error) {
        UI.fail(error, 'Could not open checkout.');
      }
    },

    portal: async function () {
      try {
        var res = await API.post('/api/payments/portal', {});
        location.href = res.url;
      } catch (error) { UI.fail(error, 'Could not open the billing portal.'); }
    },

    cancel: async function () {
      if (!confirm('Cancel your plan? It stays active until the end of the current period.')) return;
      try {
        var res = await API.post('/api/payments/cancel', {});
        UI.info('Cancellation scheduled', res.message);
      } catch (error) { UI.fail(error, 'Could not cancel.'); }
    }
  };

  global.Pricing = Pricing;
})(window);
