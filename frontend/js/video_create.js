/* Channel 12 — AI video creation. */
(function (global) {
  'use strict';

  var Video = {
    config: null,

    mount: async function (host) {
      var files = await Library.list();
      try { Video.config = await API.get('/api/video/config'); }
      catch (e) { Video.config = { allowed_qualities: ['720p'], max_duration_seconds: 60,
                                   aspect_ratios: ['16:9'], watermark: true }; }

      var cfg = Video.config;
      var maxMinutes = cfg.unlimited_length ? 60 : Math.max(1, Math.round(cfg.max_duration_seconds / 60));

      host.innerHTML =
        (cfg.visual_provider === 'generated' ? UI.notice(
          'No image provider is connected, so scenes render as typographic cards. Add PEXELS_API_KEY for ' +
          'stock footage or REPLICATE_API_KEY for generated visuals.', 'warn') : '') +
        '<div class="card">' +
          '<h2 class="card__title">Brief</h2>' +
          '<p class="card__hint">Describe what you want, or paste the exact script you want narrated.</p>' +
          '<div class="field">' +
            '<label class="field__label" for="vdPrompt">What is this video about?</label>' +
            '<textarea class="textarea" id="vdPrompt" placeholder="A three minute explainer on how drywall finishing levels work, aimed at general contractors."></textarea>' +
          '</div>' +
          '<div class="field">' +
            '<label class="field__label" for="vdScript">Exact script (optional)</label>' +
            '<textarea class="textarea" id="vdScript" placeholder="Leave blank to have the script written for you."></textarea>' +
          '</div>' +
          '<div class="grid cols-2">' +
            '<div class="field">' +
              '<label class="field__label" for="vdFile">Or adapt a file</label>' +
              '<select class="select" id="vdFile">' + UI.fileOptions(files) + '</select>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label" for="vdUrl">Or adapt a link</label>' +
              '<input class="input mono" id="vdUrl" placeholder="https://…" spellcheck="false">' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="card">' +
          '<h2 class="card__title">Format</h2>' +
          '<div class="grid cols-3">' +
            '<div class="field">' +
              '<label class="field__label" for="vdLength">Length <span class="mono" id="vdLengthVal">1:00</span></label>' +
              '<input class="range" type="range" id="vdLength" min="15" max="' + (maxMinutes * 60) +
                '" step="15" value="60">' +
              '<p class="field__note">Your plan allows ' + (cfg.unlimited_length ? 'any length' :
                maxMinutes + ' minutes') + '.</p>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label" for="vdQuality">Quality</label>' +
              '<select class="select" id="vdQuality">' +
                (cfg.allowed_qualities || []).map(function (q) {
                  return '<option value="' + q + '">' + q + '</option>';
                }).join('') + '</select>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label" for="vdAspect">Aspect</label>' +
              '<select class="select" id="vdAspect">' +
                (cfg.aspect_ratios || []).map(function (a) {
                  return '<option value="' + a + '">' + a + '</option>';
                }).join('') + '</select>' +
            '</div>' +
          '</div>' +
          '<div class="grid cols-2">' +
            '<label class="checkbox"><input type="checkbox" id="vdCaptions" checked> Burn in captions</label>' +
            '<label class="checkbox"><input type="checkbox" id="vdPriority"> Priority queue (+5 credits)</label>' +
          '</div>' +
          (cfg.watermark ? UI.notice('Free tier exports carry an OMNICRAFT watermark. Any paid plan removes it.', 'warn') : '') +
          '<div class="btn-row mt">' +
            '<button class="btn" id="vdRun">Generate video</button>' +
            '<span class="cost" id="vdCost">Costs <b>15</b> credits</span>' +
          '</div>' +
        '</div>' +
        '<div id="vdResult"></div>';

      var length = document.getElementById('vdLength');
      var quality = document.getElementById('vdQuality');
      var recost = async function () {
        document.getElementById('vdLengthVal').textContent = UI.duration(Number(length.value));
        try {
          var est = await API.post('/api/video/estimate', {
            prompt: 'estimate',
            duration_seconds: Number(length.value),
            quality: quality.value,
            priority: document.getElementById('vdPriority').checked
          });
          document.getElementById('vdCost').innerHTML = 'Costs <b>' + est.credits + '</b> credits';
        } catch (e) { /* keep the last figure */ }
      };
      length.oninput = function () {
        document.getElementById('vdLengthVal').textContent = UI.duration(Number(length.value));
      };
      length.onchange = recost;
      quality.onchange = recost;
      document.getElementById('vdPriority').onchange = recost;
      document.getElementById('vdRun').onclick = Video.run;
      recost();
    },

    run: async function () {
      var prompt = document.getElementById('vdPrompt').value.trim();
      var script = document.getElementById('vdScript').value.trim();
      var fileId = document.getElementById('vdFile').value;
      var url = document.getElementById('vdUrl').value.trim();
      if (!prompt && !script && !fileId && !url) {
        UI.warn('Give it something to work with', 'Describe the video, paste a script, or point at a source.');
        return;
      }

      var button = document.getElementById('vdRun');
      UI.busy(button, true, 'Queueing');
      try {
        var job = await API.post('/api/video/create', {
          prompt: prompt || null,
          script: script || null,
          source_file_id: fileId || null,
          source_url: url || null,
          duration_seconds: Number(document.getElementById('vdLength').value),
          quality: document.getElementById('vdQuality').value,
          aspect_ratio: document.getElementById('vdAspect').value,
          captions: document.getElementById('vdCaptions').checked,
          priority: document.getElementById('vdPriority').checked
        });
        Jobs.put(job);
        document.getElementById('vdResult').innerHTML =
          '<div class="card"><h2 class="card__title">Render</h2>' +
          '<p class="card__hint">Long videos take a while. You can leave this page — progress keeps updating.</p>' +
          '<div id="vdJobHost"></div></div>';
        Jobs.attach(document.getElementById('vdJobHost'), job.id);
        Jobs.watch(job.id, async function (finished) {
          if (finished.status !== 'completed') return;
          Library.invalidate();
          var out = finished.output_data;
          var src = await API.fetchBlobUrl(out.file_id);
          document.getElementById('vdJobHost').insertAdjacentHTML('beforeend',
            '<video class="player mt" controls src="' + src + '"></video>' +
            '<p class="muted small mt">' + out.scene_count + ' scenes · ' + UI.duration(out.duration) +
            ' · visuals: ' + UI.escape(out.visual_provider) + ' · voice: ' +
            UI.escape(out.narration_provider) + '</p>');
        });
        Auth.refreshUser();
        UI.info('Queued', 'Charged ' + job.credits_charged + ' credits.');
      } catch (error) {
        UI.fail(error, 'Could not start that render.');
      } finally {
        UI.busy(button, false);
      }
    }
  };

  global.Video = Video;
})(window);
