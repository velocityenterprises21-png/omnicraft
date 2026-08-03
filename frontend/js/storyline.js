/* Channel 05 — transcript rewriting. */
(function (global) {
  'use strict';

  var Storyline = {
    mount: async function (host) {
      var files = await Library.list();
      host.innerHTML =
        '<div class="card">' +
          '<h2 class="card__title">Source</h2>' +
          '<p class="card__hint">Paste text, pick a file, or drop in a link. One credit per run.</p>' +
          '<div class="field">' +
            '<label class="field__label" for="slText">Text</label>' +
            '<textarea class="textarea" id="slText" placeholder="Paste a transcript, article or set of notes…"></textarea>' +
          '</div>' +
          '<div class="grid cols-2">' +
            '<div class="field">' +
              '<label class="field__label" for="slFile">Or a file</label>' +
              '<select class="select" id="slFile">' + UI.fileOptions(files) + '</select>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label" for="slUrl">Or a link</label>' +
              '<input class="input mono" id="slUrl" placeholder="https://…" spellcheck="false">' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="card">' +
          '<h2 class="card__title">Shape</h2>' +
          '<div class="grid cols-3">' +
            '<div class="field">' +
              '<label class="field__label" for="slMode">Output</label>' +
              '<select class="select" id="slMode">' +
                '<option value="summary">Prose summary</option>' +
                '<option value="bullets">Bullet points</option>' +
                '<option value="clean">Cleaned transcript</option>' +
                '<option value="script">Narration script</option>' +
                '<option value="chapters">Chapter markers</option>' +
              '</select>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label" for="slTone">Tone</label>' +
              '<select class="select" id="slTone">' +
                '<option value="neutral">Neutral</option><option value="plain">Plain and direct</option>' +
                '<option value="warm">Warm</option><option value="technical">Technical</option>' +
                '<option value="punchy">Punchy</option>' +
              '</select>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label" for="slWords">Target length <span class="mono" id="slWordsVal">250</span> words</label>' +
              '<input class="range" type="range" id="slWords" min="40" max="2000" step="10" value="250">' +
            '</div>' +
          '</div>' +
          '<div class="btn-row"><button class="btn" id="slRun">Rewrite</button></div>' +
        '</div>' +
        '<div id="slResult"></div>';

      document.getElementById('slWords').oninput = function (e) {
        document.getElementById('slWordsVal').textContent = e.target.value;
      };
      document.getElementById('slRun').onclick = Storyline.run;
    },

    run: async function () {
      var text = document.getElementById('slText').value.trim();
      var fileId = document.getElementById('slFile').value;
      var url = document.getElementById('slUrl').value.trim();
      if (!text && !fileId && !url) {
        UI.warn('Nothing to work from', 'Paste text, pick a file, or add a link.');
        return;
      }

      var button = document.getElementById('slRun');
      UI.busy(button, true, 'Rewriting');
      try {
        var result = await API.post('/api/storyline/generate', {
          text: text || null,
          source_file_id: fileId || null,
          url: url || null,
          mode: document.getElementById('slMode').value,
          tone: document.getElementById('slTone').value,
          target_words: Number(document.getElementById('slWords').value)
        });
        document.getElementById('slResult').innerHTML =
          '<div class="card">' +
            '<h2 class="card__title">' + UI.escape(result.mode) + '</h2>' +
            '<p class="card__hint">' + result.word_count + ' words from ' +
              result.source_word_count.toLocaleString() + ' · engine: ' + UI.escape(result.engine) + '</p>' +
            '<div class="output">' + UI.escape(result.output) + '</div>' +
            '<div class="btn-row mt">' +
              '<button class="btn btn--ghost btn--sm" id="slCopy">Copy</button>' +
              '<button class="btn btn--quiet btn--sm" id="slShowSource">Show the source transcript</button>' +
            '</div>' +
            '<div class="output mono mt hidden" id="slSource">' + UI.escape(result.transcript) + '</div>' +
          '</div>';

        document.getElementById('slCopy').onclick = function () {
          navigator.clipboard.writeText(result.output)
            .then(function () { UI.ok('Copied', 'The rewrite is on your clipboard.'); })
            .catch(function () { UI.err('Copy blocked', 'Select the text and copy it manually.'); });
        };
        document.getElementById('slShowSource').onclick = function () {
          document.getElementById('slSource').classList.toggle('hidden');
        };
        Auth.refreshUser();
      } catch (error) {
        UI.fail(error, 'Could not rewrite that.');
      } finally {
        UI.busy(button, false);
      }
    }
  };

  global.Storyline = Storyline;
})(window);
