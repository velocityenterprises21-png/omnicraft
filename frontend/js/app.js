/* OMNICRAFT — shell, routing and the talkback deck. */
(function (global) {
  'use strict';

  var CHANNELS = [
    { id: 'overview',  no: '00', name: 'Overview',      group: 'Console',  title: 'Command centre',  sub: 'Every module in one surface' },
    { id: 'download',  no: '01', name: 'Downloader',    group: 'Capture',  title: 'Video downloader', sub: 'Pull source media', key: 'download', mount: function (h) { Download.mount(h); } },
    { id: 'tts',       no: '02', name: 'Text to speech',group: 'Capture',  title: 'Text to speech',   sub: 'Script in, voice out', key: 'tts', mount: function (h) { TTS.mount(h); } },
    { id: 'narration', no: '03', name: 'Narration',     group: 'Assemble', title: 'Narration',        sub: 'Voice over video', key: 'narration', mount: function (h) { Narration.mount(h); } },
    { id: 'subtitles', no: '04', name: 'Subtitles',     group: 'Assemble', title: 'Subtitles',        sub: 'Transcribe and translate', key: 'subtitles', mount: function (h) { Subtitles.mount(h); } },
    { id: 'storyline', no: '05', name: 'Storyline',     group: 'Assemble', title: 'Storyline',        sub: 'Rewrite a transcript', key: 'storyline', mount: function (h) { Storyline.mount(h); } },
    { id: 'rights',    no: '06', name: 'Music rights',  group: 'Assemble', title: 'Music rights',     sub: 'Screen and clear audio', key: 'rights', mount: function (h) { Rights.mount(h); } },
    { id: 'autopilot', no: '07', name: 'Autopilot',     group: 'Direct',   title: 'Autopilot',        sub: 'Describe it, we route it', key: 'autopilot', mount: function (h) { Autopilot.mount(h); } },
    { id: 'research',  no: '08', name: 'Research',      group: 'Direct',   title: 'Web research',     sub: 'Sourced briefings', key: 'research', mount: function (h) { Research.mount(h); } },
    { id: 'video',     no: '12', name: 'AI video',      group: 'Direct',   title: 'AI video',         sub: 'Brief to finished cut', key: 'video', mount: function (h) { Video.mount(h); } },
    { id: 'storage',   no: '10', name: 'Storage',       group: 'Account',  title: 'Storage',          sub: 'Your file library', key: 'storage', mount: function (h) { Storage.mount(h); } },
    { id: 'security',  no: '09', name: 'Security',      group: 'Account',  title: 'Security',         sub: 'Two-factor and API keys', mount: function (h) { Security.mount(h); } },
    { id: 'pricing',   no: '11', name: 'Plans',         group: 'Account',  title: 'Plans and credits', sub: 'Six tiers, credits never expire', key: 'payments', mount: function (h) { Pricing.mount(h); } },
    { id: 'jobs',      no: '—',  name: 'Job queue',     group: 'Account',  title: 'Jobs',             sub: 'Everything running now' },
    { id: 'admin',     no: '—',  name: 'Admin',         group: 'Account',  title: 'Admin',            sub: 'Operator console', adminOnly: true, mount: function (h) { Admin.mount(h); } }
  ];

  var PANEL_HOSTS = {
    download: 'downloadPanel', tts: 'ttsPanel', narration: 'narrationPanel',
    subtitles: 'subtitlePanel', storyline: 'storylinePanel', rights: 'rightsPanel',
    autopilot: 'autopilotPanel', research: 'researchPanel', security: 'securityPanel',
    storage: 'storagePanel', pricing: 'pricingPanel', video: 'videoPanel', admin: 'adminPanel'
  };

  var App = {
    current: null,
    mounted: {},

    start: function () {
      App.buildRail();
      App.paintStatus();
      Jobs.init();
      Jobs.load();
      Sockets.connect();
      App.deck();
      App.billingReturn();

      document.getElementById('btnAccount').onclick = function () { App.go('security'); };

      window.addEventListener('hashchange', function () {
        App.go((location.hash || '#overview').slice(1), true);
      });
      App.go((location.hash || '#overview').slice(1), true);
    },

    channels: function () {
      return CHANNELS.filter(function (c) { return !c.adminOnly || Auth.isAdmin(); });
    },

    buildRail: function () {
      var rail = document.getElementById('rail');
      var html = '';
      var group = null;
      App.channels().forEach(function (c) {
        if (c.group !== group) {
          group = c.group;
          html += '<div class="rail__group">' + group + '</div>';
        }
        html += '<button class="chan" data-go="' + c.id + '" aria-current="false">' +
          '<span class="chan__no">' + c.no + '</span>' +
          '<span class="chan__name">' + UI.escape(c.name) + '</span>' +
          '<span class="chan__led" data-led="' + (c.key || '') + '"></span>' +
        '</button>';
      });
      rail.innerHTML = html;
      rail.querySelectorAll('[data-go]').forEach(function (b) {
        b.onclick = function () { App.go(b.getAttribute('data-go')); };
      });
    },

    paintStatus: function () {
      var caps = Auth.capabilities;
      if (!caps || !caps.modules) return;

      document.querySelectorAll('[data-led]').forEach(function (led) {
        var key = led.getAttribute('data-led');
        if (!key) return;
        var mod = caps.modules[key];
        if (!mod) return;
        led.classList.add(mod.ready ? 'ready' : 'blocked');
        led.title = mod.note || 'Ready';
      });

      /* The rail LEDs are nav chrome and stay here; the overview cards
         (stats + module readiness) belong to the Dashboard module. */
      if (global.Dashboard) Dashboard.render();
    },

    go: function (id, fromHash) {
      var channel = App.channels().filter(function (c) { return c.id === id; })[0];
      if (!channel) channel = App.channels()[0];

      App.current = channel.id;
      if (!fromHash) location.hash = '#' + channel.id;

      document.querySelectorAll('.view').forEach(function (v) { v.hidden = true; });
      var view = document.getElementById('view-' + channel.id);
      if (view) view.hidden = false;

      document.querySelectorAll('[data-go]').forEach(function (b) {
        b.setAttribute('aria-current', String(b.getAttribute('data-go') === channel.id));
      });

      document.getElementById('barTitle').textContent = channel.title;
      document.getElementById('barSub').textContent = channel.sub;
      document.getElementById('stage').scrollTop = 0;

      var hostId = PANEL_HOSTS[channel.id];
      if (channel.mount && hostId && !App.mounted[channel.id]) {
        App.mounted[channel.id] = true;
        try { channel.mount(document.getElementById(hostId)); }
        catch (error) {
          App.mounted[channel.id] = false;
          document.getElementById(hostId).innerHTML =
            UI.notice('This module failed to load: ' + (error.message || error), 'warn');
        }
      }
      if (channel.id === 'overview' && global.Dashboard) Dashboard.render();
      if (channel.id === 'jobs' || channel.id === 'overview') Jobs.render();
    },

    deck: function () {
      var input = document.getElementById('deckInput');
      input.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter') return;
        var command = input.value.trim();
        if (!command) return;
        e.preventDefault();
        var planOnly = e.shiftKey;
        App.go('autopilot');
        setTimeout(function () {
          var field = document.getElementById('apCommand');
          if (field) field.value = command;
          Autopilot.go(planOnly, command);
          input.value = '';
        }, 60);
      });
    },

    billingReturn: function () {
      var params = new URLSearchParams(location.search);
      var state = params.get('billing');
      if (!state) return;
      if (state === 'success') UI.ok('Plan active', 'Your credits have been added.');
      else if (state === 'credits') UI.ok('Credits added', 'They are on your balance now.');
      else if (state === 'cancelled') UI.info('Checkout cancelled', 'Nothing was charged.');
      history.replaceState({}, '', location.pathname + location.hash);
      setTimeout(function () { Auth.refreshUser(); }, 1500);
    }
  };

  global.App = App;
  document.addEventListener('DOMContentLoaded', function () { Auth.init(); });
})(window);
