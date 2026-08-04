/* Channel 04 — subtitles and translation. */
(function (global) {
  'use strict';

  var Subtitles = {
    languages: [],

    mount: async function (host) {
      var files = await Library.list();
      try {
        var data = await API.get('/api/subtitles/languages');
        Subtitles.languages = data.languages || [];
      } catch (e) { Subtitles.languages = [{ code: 'en', name: 'English' }]; }

      var options = Subtitles.languages.map(function (l) {
        return '<option value="' + l.code + '">' + UI.escape(l.name) + '</option>';
      }).join('');

      host.innerHTML =
        '<div class="card">' +
          '<h2 class="card__title">Extract</h2>' +
          '<p class="card__hint">Transcribe speech into timed lines. Two credits.</p>' +
          '<div class="grid cols-2">' +
            '<div class="field">' +
              '<label class="field__label" for="sbFile">From your library</label>' +
              '<select class="select" id="sbFile">' + UI.fileOptions(files, ['video', 'audio']) + '</select>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label" for="sbUrl">Or a link</label>' +
              '<input class="input mono" id="sbUrl" placeholder="https://…" spellcheck="false">' +
            '</div>' +
          '</div>' +
          '<div class="grid cols-2">' +
            '<div class="field">' +
              '<label class="field__label" for="sbLang">Spoken language</label>' +
              '<select class="select" id="sbLang"><option value="auto">Detect automatically</option>' + options + '</select>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label" for="sbFormat">Output format</label>' +
              '<select class="select" id="sbFormat">' +
                '<option value="srt">SRT</option><option value="vtt">WebVTT</option>' +
                '<option value="txt">Plain text</option><option value="json">JSON</option>' +
              '</select>' +
            '</div>' +
          '</div>' +
          '<div class="btn-row"><button class="btn" id="sbExtract">Extract subtitles</button></div>' +
        '</div>' +
        '<div id="sbResult"></div>' +
        '<div class="card">' +
          '<h2 class="card__title">Translate</h2>' +
          '<p class="card__hint">Point at a subtitle file already in your library. Timings are kept exactly. Three credits.</p>' +
          '<div class="grid cols-2">' +
            '<div class="field">' +
              '<label class="field__label" for="sbTrFile">Subtitle file</label>' +
              '<select class="select" id="sbTrFile">' + UI.fileOptions(files, ['text']) + '</select>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label" for="sbTrLang">Into</label>' +
              '<select class="select" id="sbTrLang">' + options + '</select>' +
            '</div>' +
          '</div>' +
          '<div class="btn-row"><button class="btn btn--ghost" id="sbTranslate">Translate</button></div>' +
        '</div>' +
        '<div id="sbTrResult"></div>';

      document.getElementById('sbExtract').onclick = Subtitles.extract;
      document.getElementById('sbTranslate').onclick = Subtitles.translate;
    },

    extract: async function () {
      var fileId = document.getElementById('sbFile').value;
      var url = document.getElementById('sbUrl').value.trim();
      if (!fileId && !url) { UI.warn('Pick a source', 'Choose a file or paste a link.'); return; }

      var button = document.getElementById('sbExtract');
      UI.busy(button, true, 'Transcribing');
      try {
        var job = await API.post('/api/subtitles/extract', {
          file_id: fileId || null,
          url: url || null,
          language: document.getElementById('sbLang').value,
          format: document.getElementById('sbFormat').value
        });
        Jobs.put(job);
        var box = document.getElementById('sbResult');
        box.innerHTML = '<div class="card"><h2 class="card__title">Transcription</h2><div id="sbJobHost"></div></div>';
        Jobs.attach(document.getElementById('sbJobHost'), job.id);
        Jobs.watch(job.id, function (finished) {
          if (finished.status !== 'completed') return;
          var out = finished.output_data;
          document.getElementById('sbJobHost').insertAdjacentHTML('beforeend',
            '<p class="muted small mt">' + out.segments + ' lines · detected ' +
            UI.escape(out.language || 'unknown') + ' · ' + UI.escape(out.engine || '') + '</p>' +
            '<div class="output mono mt">' + UI.escape(out.preview || '') + '</div>');
          Library.invalidate();
        });
        Auth.refreshUser();
      } catch (error) {
        UI.fail(error, 'Could not extract subtitles.');
      } finally {
        UI.busy(button, false);
      }
    },

    translate: async function () {
      var fileId = document.getElementById('sbTrFile').value;
      if (!fileId) { UI.warn('Pick a subtitle file', 'Extract one first, or upload an SRT.'); return; }

      var button = document.getElementById('sbTranslate');
      UI.busy(button, true, 'Translating');
      try {
        var job = await API.post('/api/subtitles/translate', {
          file_id: fileId,
          target_language: document.getElementById('sbTrLang').value,
          format: 'srt'
        });
        Jobs.put(job);
        var box = document.getElementById('sbTrResult');
        box.innerHTML = '<div class="card"><h2 class="card__title">Translation</h2><div id="sbTrJobHost"></div></div>';
        Jobs.attach(document.getElementById('sbTrJobHost'), job.id);
        Jobs.watch(job.id, function (finished) {
          if (finished.status !== 'completed') return;
          document.getElementById('sbTrJobHost').insertAdjacentHTML('beforeend',
            '<div class="output mono mt">' + UI.escape(finished.output_data.preview || '') + '</div>');
          Library.invalidate();
        });
        Auth.refreshUser();
      } catch (error) {
        UI.fail(error, 'Could not translate that file.');
      } finally {
        UI.busy(button, false);
      }
    }
  };

  global.Subtitles = Subtitles;
})(window);
