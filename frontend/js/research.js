/* Channel 08 — web research. */
(function (global) {
  'use strict';

  var Research = {
    mount: async function (host) {
      host.innerHTML =
        '<div class="card">' +
          '<h2 class="card__title">Question</h2>' +
          '<p class="card__hint">Basic reads the top results. Deep splits the question into several searches first.</p>' +
          '<div class="field">' +
            '<textarea class="textarea" id="rsQuery" style="min-height:88px" placeholder="What changed in short-form video distribution over the last year?"></textarea>' +
          '</div>' +
          '<div class="grid cols-2">' +
            '<div class="field">' +
              '<label class="field__label" for="rsDepth">Depth</label>' +
              '<select class="select" id="rsDepth">' +
                '<option value="basic">Basic · 5 credits</option>' +
                '<option value="deep">Deep · 20 credits</option>' +
              '</select>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label" for="rsMax">Sources <span class="mono" id="rsMaxVal">8</span></label>' +
              '<input class="range" type="range" id="rsMax" min="3" max="30" value="8">' +
            '</div>' +
          '</div>' +
          '<div class="btn-row"><button class="btn" id="rsRun">Start research</button></div>' +
        '</div>' +
        '<div id="rsResult"></div>' +
        '<div class="card"><h2 class="card__title">Earlier briefings</h2><div id="rsHistory"></div></div>';

      document.getElementById('rsMax').oninput = function (e) {
        document.getElementById('rsMaxVal').textContent = e.target.value;
      };
      document.getElementById('rsRun').onclick = Research.run;

      Sockets.on('research.completed', function (m) { Research.show(m.result); Research.history(); });
      Sockets.on('research.failed', function (m) { UI.err('Research failed', m.error); });
      Sockets.on('research.progress', function (m) {
        var el = document.getElementById('rsProgress');
        if (el) {
          el.querySelector('.bar__fill').style.width = m.progress + '%';
          el.querySelector('.job__stage').textContent = m.stage;
        }
      });

      Research.history();
    },

    run: async function () {
      var query = document.getElementById('rsQuery').value.trim();
      if (!query) { UI.warn('Ask something', 'Type the question you want answered.'); return; }

      var button = document.getElementById('rsRun');
      UI.busy(button, true, 'Searching');
      try {
        var task = await API.post('/api/research', {
          query: query,
          depth: document.getElementById('rsDepth').value,
          max_sources: Number(document.getElementById('rsMax').value)
        });
        document.getElementById('rsResult').innerHTML =
          '<div class="card"><div class="job" id="rsProgress">' +
            '<div class="job__head"><span class="job__type">research</span>' +
            '<span class="badge badge--running">running</span></div>' +
            '<div class="bar"><div class="bar__fill" style="width:10%"></div></div>' +
            '<div class="job__stage">Searching</div></div></div>';
        Research.track(task.task_id);
        Auth.refreshUser();
      } catch (error) {
        UI.fail(error, 'Could not start that research run.');
      } finally {
        UI.busy(button, false);
      }
    },

    track: function (taskId) {
      var tries = 0;
      var timer = setInterval(async function () {
        tries += 1;
        if (tries > 200) { clearInterval(timer); return; }
        try {
          var task = await API.get('/api/research/' + taskId);
          if (task.status === 'completed') {
            clearInterval(timer);
            Research.show(task.results);
            Research.history();
          } else if (task.status === 'failed') {
            clearInterval(timer);
            UI.err('Research failed', task.error_message || 'Credits were refunded.');
          }
        } catch (e) { /* transient */ }
      }, 4000);
    },

    show: function (result) {
      if (!result) return;
      var sources = (result.sources || []).map(function (s, i) {
        return '<div class="source">' +
          '<div class="source__title"><span class="mono muted">[' + (i + 1) + ']</span> ' +
            UI.escape(s.title) + '</div>' +
          '<a class="source__url" href="' + UI.escape(s.url) + '" target="_blank" rel="noopener noreferrer">' +
            UI.escape(s.url) + '</a></div>';
      }).join('');

      var host = document.getElementById('rsResult');
      if (!host) return;
      host.innerHTML =
        '<div class="card">' +
          '<h2 class="card__title">' + UI.escape(result.query || 'Briefing') + '</h2>' +
          '<p class="card__hint">' + (result.sources || []).length + ' sources · ' +
            UI.escape(result.depth || '') + ' · engine: ' + UI.escape(result.engine || '') + '</p>' +
          '<div class="output">' + UI.escape(result.report || '') + '</div>' +
          (result.file_id
            ? '<div class="btn-row mt"><button class="btn btn--ghost btn--sm" data-download="' +
              result.file_id + '" data-name="research-report.md">Download the report</button></div>'
            : '') +
        '</div>' +
        (sources ? '<div class="card"><h2 class="card__title">Sources</h2>' + sources + '</div>' : '');
    },

    history: async function () {
      var host = document.getElementById('rsHistory');
      if (!host) return;
      try {
        var data = await API.get('/api/research');
        host.innerHTML = data.tasks.length
          ? data.tasks.slice(0, 12).map(function (t) {
              return '<div class="file"><div class="file__kind">' + UI.escape(t.depth) + '</div>' +
                '<div><div class="file__name">' + UI.escape(t.query) + '</div>' +
                '<div class="file__meta">' + UI.escape(t.status) + ' · ' + UI.date(t.created_at) + '</div></div>' +
                '<div class="file__actions"><button class="btn btn--ghost btn--sm" data-research="' +
                t.id + '">Open</button></div></div>';
            }).join('')
          : '<p class="muted small">Nothing yet.</p>';
      } catch (e) {
        host.innerHTML = '<p class="muted small">Could not load history.</p>';
      }
    }
  };

  document.addEventListener('click', async function (e) {
    var button = e.target.closest('[data-research]');
    if (!button) return;
    try {
      var task = await API.get('/api/research/' + button.getAttribute('data-research'));
      Research.show(task.results);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (error) { UI.fail(error, 'Could not open that briefing.'); }
  });

  global.Research = Research;
})(window);
