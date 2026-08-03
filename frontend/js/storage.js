/* Channel 10 — the file library. Also exposes Library, used by every other channel. */
(function (global) {
  'use strict';

  var Library = {
    cache: null,

    list: async function (force) {
      if (this.cache && !force) return this.cache;
      try {
        var data = await API.get('/api/storage/files?limit=300');
        this.cache = data.files || [];
      } catch (e) {
        this.cache = [];
      }
      return this.cache;
    },

    invalidate: function () { this.cache = null; }
  };

  var Storage = {
    mount: async function (host) {
      host.innerHTML =
        '<div class="grid cols-3 mb" id="stUsage"></div>' +
        '<div class="card">' +
          '<div class="drop" id="stDrop">' +
            '<div class="drop__title">Drop files here</div>' +
            '<div class="drop__hint">Or click to browse. Video, audio, images and subtitle files.</div>' +
          '</div>' +
          '<input type="file" id="stInput" multiple hidden>' +
          '<div id="stProgress"></div>' +
        '</div>' +
        '<div class="card">' +
          '<div class="btn-row mb">' +
            '<h2 class="card__title" style="margin:0">Files</h2>' +
            '<span class="job__spacer" style="flex:1"></span>' +
            '<select class="select" id="stFilter" style="width:auto">' +
              '<option value="">Everything</option><option value="video">Video</option>' +
              '<option value="audio">Audio</option><option value="text">Text</option>' +
              '<option value="image">Images</option>' +
            '</select>' +
          '</div>' +
          '<div id="stFiles"></div>' +
        '</div>';

      var drop = document.getElementById('stDrop');
      var input = document.getElementById('stInput');
      drop.onclick = function () { input.click(); };
      input.onchange = function () { Storage.upload(Array.from(input.files)); input.value = ''; };
      UI.dropzone(drop, Storage.upload);
      document.getElementById('stFilter').onchange = function () { Storage.paintFiles(); };

      await Storage.paintUsage();
      await Storage.paintFiles();
    },

    paintUsage: async function () {
      var host = document.getElementById('stUsage');
      if (!host) return;
      try {
        var usage = await API.get('/api/storage/usage');
        host.innerHTML =
          '<div class="stat"><div class="stat__label">Used</div><div class="stat__value">' +
            UI.bytes(usage.used_bytes) + '</div></div>' +
          '<div class="stat"><div class="stat__label">Of your limit</div><div class="stat__value">' +
            UI.bytes(usage.limit_bytes) + '</div>' +
            '<div class="bar mt"><div class="bar__fill" style="width:' +
              Math.min(100, usage.percent) + '%"></div></div></div>' +
          '<div class="stat"><div class="stat__label">Files</div><div class="stat__value">' +
            usage.file_count + '</div></div>';
      } catch (e) {
        host.innerHTML = '';
      }
    },

    paintFiles: async function () {
      var host = document.getElementById('stFiles');
      if (!host) return;
      var filter = document.getElementById('stFilter').value;
      var files = await Library.list(true);
      if (filter) files = files.filter(function (f) { return f.kind === filter; });

      host.innerHTML = files.length ? files.map(function (f) {
        return '<div class="file">' +
          '<div class="file__kind">' + UI.escape(f.kind) + '</div>' +
          '<div><div class="file__name">' + UI.escape(f.filename) + '</div>' +
          '<div class="file__meta">' + UI.bytes(f.file_size) +
            (f.duration_seconds ? ' · ' + UI.duration(f.duration_seconds) : '') +
            ' · ' + UI.date(f.created_at) + '</div></div>' +
          '<div class="file__actions">' +
            '<button class="btn btn--ghost btn--sm" data-download="' + f.id + '" data-name="' +
              UI.escape(f.filename) + '">Get</button>' +
            '<button class="btn btn--quiet btn--sm" data-share="' + f.id + '">Share</button>' +
            '<button class="btn btn--danger btn--sm" data-remove="' + f.id + '">Delete</button>' +
          '</div></div>';
      }).join('')
        : UI.empty('Nothing stored yet', 'Upload something, or run a job — output lands here automatically.');
    },

    upload: async function (files) {
      var host = document.getElementById('stProgress');
      for (var i = 0; i < files.length; i++) {
        var file = files[i];
        var row = document.createElement('div');
        row.className = 'job mt';
        row.innerHTML = '<div class="job__head"><span class="job__type">' + UI.escape(file.name) +
          '</span><span class="job__spacer"></span><span class="job__pct">0%</span></div>' +
          '<div class="bar"><div class="bar__fill"></div></div>';
        host.appendChild(row);

        try {
          /* eslint-disable no-await-in-loop */
          await API.upload(file, function (pct) {
            row.querySelector('.bar__fill').style.width = pct + '%';
            row.querySelector('.job__pct').textContent = pct + '%';
          });
          row.querySelector('.bar__fill').classList.add('done');
          UI.ok('Uploaded', file.name);
        } catch (error) {
          row.querySelector('.bar__fill').classList.add('failed');
          UI.fail(error, 'Upload failed.');
        }
      }
      Library.invalidate();
      await Storage.paintUsage();
      await Storage.paintFiles();
      setTimeout(function () { host.innerHTML = ''; }, 3000);
    }
  };

  document.addEventListener('click', async function (e) {
    var share = e.target.closest('[data-share]');
    var remove = e.target.closest('[data-remove]');

    if (share) {
      try {
        var link = await API.post('/api/storage/share/' + share.getAttribute('data-share'),
                                  { expires_in_hours: 72 });
        await navigator.clipboard.writeText(link.url).catch(function () {});
        UI.ok('Share link copied', 'It works for 72 hours, then stops.');
      } catch (error) { UI.fail(error, 'Could not create a share link.'); }
    }

    if (remove) {
      if (!confirm('Delete this file? It can\'t be recovered.')) return;
      try {
        await API.del('/api/storage/files/' + remove.getAttribute('data-remove'));
        Library.invalidate();
        await Storage.paintUsage();
        await Storage.paintFiles();
        UI.info('Deleted', 'The file is gone and the space is back.');
      } catch (error) { UI.fail(error, 'Could not delete that file.'); }
    }
  });

  global.Library = Library;
  global.Storage = Storage;
})(window);
