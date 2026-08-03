/* Channel 01 — retrieval. */
(function (global) {
  'use strict';

  var Download = {
    mount: function (host) {
      host.innerHTML =
        '<div class="card">' +
          '<h2 class="card__title">Source link</h2>' +
          '<p class="card__hint">YouTube, Instagram, TikTok, Facebook, X, Vimeo, Dailymotion, Twitch, SoundCloud and Reddit.</p>' +
          '<div class="field">' +
            '<label class="field__label" for="dlUrl">URL</label>' +
            '<input class="input mono" id="dlUrl" placeholder="https://…" spellcheck="false">' +
          '</div>' +
          '<div class="grid cols-2">' +
            '<div class="field">' +
              '<label class="field__label" for="dlQuality">Quality</label>' +
              '<select class="select" id="dlQuality">' +
                '<option value="best">Best available</option>' +
                '<option value="2160p">2160p</option>' +
                '<option value="1440p">1440p</option>' +
                '<option value="1080p">1080p</option>' +
                '<option value="720p">720p</option>' +
                '<option value="480p">480p</option>' +
              '</select>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label">Options</label>' +
              '<label class="checkbox"><input type="checkbox" id="dlAudio"> Audio only (MP3)</label>' +
              '<label class="checkbox mt"><input type="checkbox" id="dlPriority"> Priority queue (+5 credits)</label>' +
            '</div>' +
          '</div>' +
          '<div class="btn-row mt">' +
            '<button class="btn btn--ghost" id="dlInspect">Inspect first</button>' +
            '<button class="btn" id="dlStart">Download</button>' +
            '<span class="cost" id="dlCost"></span>' +
          '</div>' +
        '</div>' +
        '<div id="dlPreview"></div>' +
        '<div id="dlJobs"></div>';

      document.getElementById('dlInspect').onclick = Download.inspect;
      document.getElementById('dlStart').onclick = Download.start;
      document.getElementById('dlUrl').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') Download.start();
      });
    },

    payload: function () {
      return {
        url: document.getElementById('dlUrl').value.trim(),
        quality: document.getElementById('dlQuality').value,
        audio_only: document.getElementById('dlAudio').checked,
        priority: document.getElementById('dlPriority').checked
      };
    },

    inspect: async function () {
      var body = Download.payload();
      if (!body.url) { UI.warn('Add a link', 'Paste the URL you want to pull.'); return; }
      var button = document.getElementById('dlInspect');
      UI.busy(button, true, 'Reading');
      try {
        var info = await API.post('/api/download/probe', body);
        document.getElementById('dlCost').innerHTML = 'Costs <b>' + info.estimated_credits + '</b> credits';
        document.getElementById('dlPreview').innerHTML =
          '<div class="card">' +
            '<h2 class="card__title">' + UI.escape(info.title || 'Untitled') + '</h2>' +
            '<p class="card__hint">' + UI.escape(info.uploader || 'Unknown uploader') + ' · ' +
              UI.escape(info.extractor || '') + '</p>' +
            '<div class="grid cols-3">' +
              '<div class="stat"><div class="stat__label">Length</div><div class="stat__value">' +
                UI.duration(info.duration) + '</div></div>' +
              '<div class="stat"><div class="stat__label">Resolution</div><div class="stat__value">' +
                (info.width ? info.width + '×' + info.height : '—') + '</div></div>' +
              '<div class="stat"><div class="stat__label">Credits</div><div class="stat__value">' +
                info.estimated_credits + '</div></div>' +
            '</div>' +
            '<div class="notice mt">' +
              '<span class="notice__mark">!</span>' +
              '<div>Check you hold the rights before you publish anything from this source.</div>' +
            '</div>' +
          '</div>';
      } catch (error) {
        UI.fail(error, 'Could not read that link.');
      } finally {
        UI.busy(button, false);
      }
    },

    start: async function () {
      var body = Download.payload();
      if (!body.url) { UI.warn('Add a link', 'Paste the URL you want to pull.'); return; }
      var button = document.getElementById('dlStart');
      UI.busy(button, true, 'Queueing');
      try {
        var job = await API.post('/api/download', body);
        UI.info('Queued', 'Charged ' + job.credits_charged + ' credits.');
        Jobs.put(job);
        Jobs.attach(document.getElementById('dlJobs'), job.id);
        Auth.refreshUser();
      } catch (error) {
        UI.fail(error, 'Could not start that download.');
      } finally {
        UI.busy(button, false);
      }
    }
  };

  global.Download = Download;
})(window);
