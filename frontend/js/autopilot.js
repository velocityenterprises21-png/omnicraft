/* Channel 07 — natural language orchestration. */
(function (global) {
  'use strict';

  var Autopilot = {
    mount: async function (host) {
      var meta = await API.get('/api/autopilot/capabilities').catch(function () { return { capabilities: {} }; });
      var list = Object.keys(meta.capabilities || {}).map(function (key) {
        return '<div class="source"><div class="source__title">' + UI.escape(key) + '</div>' +
               '<div class="small muted">' + UI.escape(meta.capabilities[key]) + '</div></div>';
      }).join('');

      host.innerHTML =
        '<div class="card">' +
          '<h2 class="card__title">Instruction</h2>' +
          '<p class="card__hint">Plain language. Include links and the format you want back.</p>' +
          '<textarea class="textarea" id="apCommand" placeholder="Pull the audio from this talk, transcribe it, translate the subtitles into Spanish, and give me the key points as bullets."></textarea>' +
          '<div class="btn-row mt">' +
            '<button class="btn btn--ghost" id="apPlan">Show me the plan</button>' +
            '<button class="btn" id="apRun">Plan and run</button>' +
            '<span class="muted small">Planner: ' + UI.escape(meta.planner || 'keyword') + '</span>' +
          '</div>' +
        '</div>' +
        '<div id="apResult"></div>' +
        '<div class="card">' +
          '<h2 class="card__title">What it can reach</h2>' +
          '<p class="card__hint">Autopilot only calls these modules. Anything else it will tell you it can\'t do.</p>' +
          list +
        '</div>';

      document.getElementById('apPlan').onclick = function () { Autopilot.go(true); };
      document.getElementById('apRun').onclick = function () { Autopilot.go(false); };
    },

    go: async function (planOnly, presetCommand) {
      var input = document.getElementById('apCommand');
      var command = presetCommand || (input ? input.value.trim() : '');
      if (!command) { UI.warn('Say what you want', 'Describe the outcome and Autopilot works out the steps.'); return; }
      if (input && presetCommand) input.value = presetCommand;

      var button = document.getElementById(planOnly ? 'apPlan' : 'apRun');
      UI.busy(button, true, planOnly ? 'Planning' : 'Running');
      try {
        var result = planOnly
          ? await API.post('/api/autopilot/plan', { command: command })
          : await API.post('/api/autopilot/run', { command: command, dry_run: false });
        Autopilot.paint(result, planOnly, command);
        Auth.refreshUser();
      } catch (error) {
        UI.fail(error, 'Autopilot could not run that.');
      } finally {
        UI.busy(button, false);
      }
    },

    paint: function (result, planOnly, command) {
      var steps = (result.steps || []).map(function (s, i) {
        return '<div class="source">' +
          '<div class="source__title"><span class="mono muted">' + String(i + 1).padStart(2, '0') + '</span> ' +
            UI.escape(s.action) + '</div>' +
          '<div class="small muted">' + UI.escape(s.why || JSON.stringify(s.args || {})) + '</div>' +
        '</div>';
      }).join('') || '<p class="muted small">No steps matched that request.</p>';

      var host = document.getElementById('apResult');
      host.innerHTML =
        '<div class="card">' +
          '<h2 class="card__title">Plan</h2>' +
          '<p class="card__hint">' + (result.steps || []).length + ' step(s) · about ' +
            result.estimated_credits + ' credits · planner: ' + UI.escape(result.planner || '') + '</p>' +
          steps +
          (planOnly
            ? '<div class="btn-row mt"><button class="btn" id="apConfirm">Run this plan</button></div>'
            : '') +
          '<div id="apDispatch" class="mt"></div>' +
        '</div>';

      if (planOnly) {
        document.getElementById('apConfirm').onclick = function () { Autopilot.go(false, command); };
        return;
      }

      var dispatch = document.getElementById('apDispatch');
      (result.dispatched || []).forEach(function (item) {
        if (item.kind === 'job') {
          Jobs.attach(dispatch, item.job_id);
        } else if (item.kind === 'research') {
          dispatch.insertAdjacentHTML('beforeend',
            '<div class="notice notice--ok"><span class="notice__mark">→</span><div>Research task started. ' +
            'Open the Research channel to read the briefing.</div></div>');
          if (global.Research) Research.track(item.task_id);
        } else if (item.kind === 'inline') {
          dispatch.insertAdjacentHTML('beforeend',
            '<div class="card"><h2 class="card__title">' + UI.escape(item.action) + '</h2>' +
            '<div class="output">' + UI.escape((item.result && item.result.output) || '') + '</div></div>');
        } else {
          var reason = item.reason;
          if (reason && typeof reason === 'object') reason = reason.message || JSON.stringify(reason);
          dispatch.insertAdjacentHTML('beforeend',
            UI.notice(item.action + ': ' + (reason || 'skipped'), 'warn'));
        }
      });
    }
  };

  global.Autopilot = Autopilot;
})(window);
