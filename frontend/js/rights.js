/* Channel 06 — music rights screening and clearance. */
(function (global) {
  'use strict';

  var Rights = {
    lastScan: null,

    mount: async function (host) {
      var files = await Library.list();
      var meta = await API.get('/api/rights/actions').catch(function () { return { actions: [] }; });

      host.innerHTML =
        (meta.identification ? '' : UI.notice(
          'Automatic recording identification isn\'t configured. Add ACOUSTID_API_KEY and the fpcalc ' +
          'binary to screen uploads against the recording database. The clearance tools below still work.',
          'warn')) +
        '<div class="card">' +
          '<h2 class="card__title">Screen a file</h2>' +
          '<p class="card__hint">Fingerprints the audio and checks it against the commercial recording database. Two credits.</p>' +
          '<select class="select mb" id="rtFile">' + UI.fileOptions(files, ['video', 'audio']) + '</select>' +
          '<div class="btn-row"><button class="btn" id="rtScan">Run the scan</button></div>' +
        '</div>' +
        '<div id="rtResult"></div>' +
        '<div class="card">' +
          '<h2 class="card__title">What clearance means here</h2>' +
          '<p class="card__hint">These tools remove or replace material you don\'t hold rights to. ' +
            'They don\'t disguise a protected recording so it slips past a claim — if you have a licence, ' +
            'keep the paperwork and publish as is.</p>' +
          (meta.actions || []).map(function (a) {
            return '<div class="source"><div class="source__title">' + UI.escape(a.label) + '</div>' +
                   '<div class="small muted">' + UI.escape(a.detail) + '</div></div>';
          }).join('') +
        '</div>';

      document.getElementById('rtScan').onclick = Rights.scan;
    },

    scan: async function () {
      var fileId = document.getElementById('rtFile').value;
      if (!fileId) { UI.warn('Pick a file', 'Choose the video or audio to screen.'); return; }

      var button = document.getElementById('rtScan');
      UI.busy(button, true, 'Screening');
      try {
        var result = await API.post('/api/rights/scan', { file_id: fileId });
        Rights.lastScan = result;
        Rights.paint(result, fileId);
        Auth.refreshUser();
      } catch (error) {
        UI.fail(error, 'Screening failed.');
      } finally {
        UI.busy(button, false);
      }
    },

    paint: async function (result, fileId) {
      var files = await Library.list();
      var tone = result.status === 'matched' ? 'live' : (result.status === 'clear' ? 'ok' : 'warn');
      var rows = (result.matches || []).map(function (m) {
        return '<tr><td>' + UI.escape(m.title || 'Unknown') + '</td>' +
               '<td>' + UI.escape((m.artists || []).join(', ') || '—') + '</td>' +
               '<td class="num">' + (m.confidence != null ? m.confidence : '—') + '</td>' +
               '<td class="num">' + UI.duration(m.start) + ' – ' + UI.duration(m.end) + '</td></tr>';
      }).join('');

      document.getElementById('rtResult').innerHTML =
        '<div class="card">' +
          '<h2 class="card__title">Screening result</h2>' +
          UI.notice(result.message, tone) +
          (rows ? '<div class="table-wrap"><table class="table"><thead><tr>' +
            '<th>Recording</th><th>Artist</th><th>Confidence</th><th>Range</th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table></div>' : '') +
          '<div class="grid cols-2 mt">' +
            '<div class="field">' +
              '<label class="field__label" for="rtAction">Clearance action</label>' +
              '<select class="select" id="rtAction">' +
                '<option value="mute">Mute the flagged range</option>' +
                '<option value="remove_music">Remove the music bed, keep dialogue</option>' +
                '<option value="replace">Swap in a licensed track</option>' +
              '</select>' +
            '</div>' +
            '<div class="field">' +
              '<label class="field__label" for="rtTrack">Your licensed track</label>' +
              '<select class="select" id="rtTrack">' + UI.fileOptions(files, ['audio']) + '</select>' +
              '<p class="field__note">Only used by the swap action.</p>' +
            '</div>' +
          '</div>' +
          '<div class="btn-row">' +
            '<button class="btn" id="rtApply">Apply clearance</button>' +
            '<span class="cost">Costs <b>3</b> credits</span>' +
          '</div>' +
          '<div id="rtJobHost"></div>' +
        '</div>';

      document.getElementById('rtApply').onclick = function () { Rights.apply(fileId, result); };
    },

    apply: async function (fileId, scan) {
      var action = document.getElementById('rtAction').value;
      var track = document.getElementById('rtTrack').value;
      if (action === 'replace' && !track) {
        UI.warn('Pick a track', 'Choose the licensed audio you want laid underneath.');
        return;
      }
      var segments = (scan.matches || []).map(function (m) {
        return { start: m.start || 0, end: m.end || 0 };
      });

      var button = document.getElementById('rtApply');
      UI.busy(button, true, 'Clearing');
      try {
        var job = await API.post('/api/rights/remediate', {
          file_id: fileId,
          action: action,
          replacement_track_id: track || null,
          segments: segments.length ? segments : null
        });
        Jobs.put(job);
        Jobs.attach(document.getElementById('rtJobHost'), job.id);
        Jobs.watch(job.id, function (finished) {
          if (finished.status === 'completed') Library.invalidate();
        });
        Auth.refreshUser();
      } catch (error) {
        UI.fail(error, 'Clearance failed.');
      } finally {
        UI.busy(button, false);
      }
    }
  };

  global.Rights = Rights;
})(window);
