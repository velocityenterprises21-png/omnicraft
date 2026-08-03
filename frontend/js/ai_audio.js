/* Channel 02 — text to speech. */
(function (global) {
  'use strict';

  var TTS = {
    voices: [],

    mount: async function (host) {
      host.innerHTML =
        '<div class="card">' +
          '<h2 class="card__title">Script</h2>' +
          '<p class="card__hint">Roughly 900 characters becomes a minute of speech. Two credits a minute.</p>' +
          '<textarea class="textarea" id="ttsText" placeholder="Paste the words you want spoken…"></textarea>' +
          '<div class="grid cols-3 mt">' +
            '<div class="field">' +
              '<label class="field__label" for="ttsVoice">Voice</label>' +
              '<select class="select" id="ttsVoice"><option>Loading…</option></select>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label" for="ttsSpeed">Pace <span class="mono" id="ttsSpeedVal">1.00×</span></label>' +
              '<input class="range" type="range" id="ttsSpeed" min="0.5" max="2" step="0.05" value="1">' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label" for="ttsStability">Steadiness <span class="mono" id="ttsStabVal">0.50</span></label>' +
              '<input class="range" type="range" id="ttsStability" min="0" max="1" step="0.05" value="0.5">' +
            '</div>' +
          '</div>' +
          '<label class="checkbox"><input type="checkbox" id="ttsPriority"> Priority queue (+5 credits)</label>' +
          '<div class="btn-row mt">' +
            '<button class="btn" id="ttsRun">Render voiceover</button>' +
            '<span class="cost" id="ttsCost">Costs <b>0</b> credits</span>' +
            '<span class="muted small" id="ttsProvider"></span>' +
          '</div>' +
        '</div>' +
        '<div id="ttsResult"></div>';

      var text = document.getElementById('ttsText');
      text.oninput = function () {
        var credits = Math.max(1, Math.ceil(text.value.length / 900)) * 2 +
                      (document.getElementById('ttsPriority').checked ? 5 : 0);
        document.getElementById('ttsCost').innerHTML =
          'Costs <b>' + (text.value.length ? credits : 0) + '</b> credits · ' +
          text.value.length.toLocaleString() + ' characters';
      };
      document.getElementById('ttsSpeed').oninput = function (e) {
        document.getElementById('ttsSpeedVal').textContent = Number(e.target.value).toFixed(2) + '×';
      };
      document.getElementById('ttsStability').oninput = function (e) {
        document.getElementById('ttsStabVal').textContent = Number(e.target.value).toFixed(2);
      };
      document.getElementById('ttsPriority').onchange = function () { text.oninput(); };
      document.getElementById('ttsRun').onclick = TTS.run;

      try {
        var data = await API.get('/api/tts/voices');
        TTS.voices = data.voices || [];
        document.getElementById('ttsVoice').innerHTML = TTS.voices.map(function (v) {
          return '<option value="' + v.id + '">' + UI.escape(v.name) +
                 (v.tone ? ' · ' + UI.escape(v.tone) : '') + '</option>';
        }).join('');
        document.getElementById('ttsProvider').textContent = 'Engine: ' + data.provider;
        if (data.notice) host.insertAdjacentHTML('afterbegin', UI.notice(data.notice, 'warn'));
      } catch (error) {
        document.getElementById('ttsVoice').innerHTML = '<option value="default">Default</option>';
      }
    },

    run: async function () {
      var text = document.getElementById('ttsText').value.trim();
      if (!text) { UI.warn('Nothing to speak', 'Paste a script first.'); return; }
      var button = document.getElementById('ttsRun');
      UI.busy(button, true, 'Rendering');
      try {
        var job = await API.post('/api/tts/generate', {
          text: text,
          voice_id: document.getElementById('ttsVoice').value,
          speed: Number(document.getElementById('ttsSpeed').value),
          stability: Number(document.getElementById('ttsStability').value),
          priority: document.getElementById('ttsPriority').checked
        });
        Jobs.put(job);
        var result = document.getElementById('ttsResult');
        result.innerHTML = '<div class="card"><h2 class="card__title">Render</h2><div id="ttsJobHost"></div></div>';
        Jobs.attach(document.getElementById('ttsJobHost'), job.id);
        Jobs.watch(job.id, async function (finished) {
          if (finished.status !== 'completed') return;
          var url = await API.fetchBlobUrl(finished.output_data.file_id);
          document.getElementById('ttsJobHost').insertAdjacentHTML('beforeend',
            '<audio class="player mt" controls src="' + url + '"></audio>');
        });
        Auth.refreshUser();
      } catch (error) {
        UI.fail(error, 'Could not render that voiceover.');
      } finally {
        UI.busy(button, false);
      }
    }
  };

  global.TTS = TTS;
})(window);
