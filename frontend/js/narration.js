/* Channel 03 — narration mix. */
(function (global) {
  'use strict';

  var Narration = {
    mount: async function (host) {
      var files = await Library.list();
      host.innerHTML =
        '<div class="card">' +
          '<h2 class="card__title">Video</h2>' +
          '<p class="card__hint">Pick something from your library. Upload from the Storage channel if it isn\'t there yet.</p>' +
          '<select class="select" id="nrVideo">' + UI.fileOptions(files, ['video']) + '</select>' +
        '</div>' +
        '<div class="card">' +
          '<h2 class="card__title">Voice</h2>' +
          '<p class="card__hint">Write a script and we\'ll speak it, or bring your own audio.</p>' +
          '<div class="field">' +
            '<label class="field__label" for="nrScript">Script</label>' +
            '<textarea class="textarea" id="nrScript" placeholder="What the narrator says…"></textarea>' +
          '</div>' +
          '<div class="field">' +
            '<label class="field__label" for="nrAudio">Or an existing audio file</label>' +
            '<select class="select" id="nrAudio">' + UI.fileOptions(files, ['audio']) + '</select>' +
          '</div>' +
        '</div>' +
        '<div class="card">' +
          '<h2 class="card__title">Mix</h2>' +
          '<div class="grid cols-3">' +
            '<div class="field">' +
              '<label class="field__label" for="nrMode">How to combine</label>' +
              '<select class="select" id="nrMode">' +
                '<option value="mix">Blend under the narration</option>' +
                '<option value="duck">Duck the original when the voice speaks</option>' +
                '<option value="replace">Replace the original audio</option>' +
              '</select>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label">Original level <span class="mono" id="nrOrigVal">0.20</span></label>' +
              '<input class="range" type="range" id="nrOrig" min="0" max="1" step="0.05" value="0.2">' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label">Voice level <span class="mono" id="nrVoiceVal">1.00</span></label>' +
              '<input class="range" type="range" id="nrVoice" min="0" max="1.5" step="0.05" value="1">' +
            '</div>' +
          '</div>' +
          '<div class="btn-row mt">' +
            '<button class="btn" id="nrRun">Mix narration</button>' +
            '<span class="cost">Costs <b>5</b> credits, plus the voiceover</span>' +
          '</div>' +
        '</div>' +
        '<div id="nrResult"></div>';

      document.getElementById('nrOrig').oninput = function (e) {
        document.getElementById('nrOrigVal').textContent = Number(e.target.value).toFixed(2);
      };
      document.getElementById('nrVoice').oninput = function (e) {
        document.getElementById('nrVoiceVal').textContent = Number(e.target.value).toFixed(2);
      };
      document.getElementById('nrRun').onclick = Narration.run;
    },

    run: async function () {
      var video = document.getElementById('nrVideo').value;
      var script = document.getElementById('nrScript').value.trim();
      var audio = document.getElementById('nrAudio').value;
      if (!video) { UI.warn('Pick a video', 'Choose the clip you want to narrate.'); return; }
      if (!script && !audio) { UI.warn('Add a voice', 'Write a script or choose an audio file.'); return; }

      var button = document.getElementById('nrRun');
      UI.busy(button, true, 'Mixing');
      try {
        var job = await API.post('/api/narrate', {
          video_file_id: video,
          script: script || null,
          audio_file_id: audio || null,
          mode: document.getElementById('nrMode').value,
          original_volume: Number(document.getElementById('nrOrig').value),
          narration_volume: Number(document.getElementById('nrVoice').value)
        });
        Jobs.put(job);
        var result = document.getElementById('nrResult');
        result.innerHTML = '<div class="card"><h2 class="card__title">Mix</h2><div id="nrJobHost"></div></div>';
        Jobs.attach(document.getElementById('nrJobHost'), job.id);
        Jobs.watch(job.id, async function (finished) {
          if (finished.status !== 'completed') return;
          var url = await API.fetchBlobUrl(finished.output_data.file_id);
          document.getElementById('nrJobHost').insertAdjacentHTML('beforeend',
            '<video class="player mt" controls src="' + url + '"></video>');
        });
        Auth.refreshUser();
      } catch (error) {
        UI.fail(error, 'Could not mix that narration.');
      } finally {
        UI.busy(button, false);
      }
    }
  };

  global.Narration = Narration;
})(window);
