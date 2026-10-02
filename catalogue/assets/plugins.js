/* BenchWeave plugin catalogue (issue #224 slice 2 + the records-table
   follow-on). Plain JS, no build chain, no dependencies beyond the vendored
   htmx (the drill-down enhancement, #224 follow-on §2.5). Two halves:

   1. PURE: filterRows(rows, query) (the search predicate — data in, data
      out, no DOM) and rowSlots(row) (the display projection for one row).
      Both are exported to CommonJS behind a typeof module guard so node can
      require this file and prove them against the hand-derived truth table
      (tests/run_search_spec.mjs) — one line of toolchain-free seam, no
      bundler.
   2. WIRING (browser only): fetch the same-origin generated index.json,
      drive the filter form over the records table, render non-default rows
      on demand from the generated template row (htmx.process applied), keep
      the caption/snapshot/empty states honest, round-trip filter state
      through the URL (the mockup's hx-push-url intent, §2.2), toggle the
      colour theme, and let htmx drive the drill-down into each row's detail
      host. On fetch failure the committed static rows stand untouched and a
      notice appears — loud degradation, never a blank page.

   The default view (CR-22) is admitted releases with a valid signature:
   exactly the rows the generated page's static rows carry. Everything else
   is reachable only through explicit filters, and renders with its kind
   badge (CR-56). Version and compatibility stamp STATICALLY in rows (the
   follow-on §2.3 — row data is data); the no-JS view is the honest default
   view. */

/* The two slice-1 unverified markers' display strings — a TWIN of
   scripts/generate_catalogue_page.py MARKER_DISPLAY, pinned byte-equal by
   tests/test_catalogue_page.py. Unknown marker ids render verbatim
   (forward-honest, never dropped). */
var MARKER_DISPLAY = {
  'conformance-evidence-self-attested': 'conformance evidence self-attested',
  'review-is-process-not-proof': 'review is process, not proof'
};

/* Kind badge text — a TWIN of the generator's KIND_DISPLAY (the mockup's
   display case; CR-56: a row never renders without its kind badge). */
var KIND_DISPLAY = {
  'admitted-release': 'Admitted release',
  'community-shared': 'Community shared',
  'in-tree-fixture': 'In-tree fixture'
};

/* Maintenance badge text + tone (the mockup's tone remapping) — TWINS of
   the generator's MAINTENANCE_DISPLAY / MAINTENANCE_BADGE. */
var MAINTENANCE_DISPLAY = {
  'maintained': 'Maintained',
  'maintenance_only': 'Maintenance only',
  'unmaintained': 'Unmaintained',
  'unknown': 'Unknown'
};
var MAINTENANCE_BADGE = {
  'maintained': 'badge-version',
  'maintenance_only': 'badge-version',
  'unmaintained': 'badge-warning',
  'unknown': 'badge-muted'
};

/* (R2, pivot §4) The digest/revision display truncation length — a TWIN of
   scripts/generate_catalogue_page.py TRUNCATE_AT, pinned equal by
   tests/test_catalogue_page.py. One constant, two carriers. */
var TRUNCATE_AT = 12;

var DEFAULT_QUERY = { kind: 'admitted-release', signature_state: 'signed-valid' };

/* Lucide icon bodies for cloned rows — TWINS of the generator's ICONS
   (every body is circle/rect-free; §2.8's icon-rewrite pick). */
var ICONS = {
  signature:
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21 17-2.156-1.868A.5.5 0 0 0 18 15.5v.5a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1c0-2.545-3.991-3.97-8.5-4a1 1 0 0 0 0 5c4.153 0 4.745-11.295 5.708-13.5a2.5 2.5 0 1 1 3.31 3.284"></path><path d="M3 21h18"></path></svg>',
  circleDashed:
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.1 2.182a10 10 0 0 1 3.8 0"></path><path d="M13.9 21.818a10 10 0 0 1-3.8 0"></path><path d="M17.609 3.721a10 10 0 0 1 2.69 2.7"></path><path d="M2.182 13.9a10 10 0 0 1 0-3.8"></path><path d="M20.279 17.609a10 10 0 0 1-2.7 2.69"></path><path d="M21.818 10.1a10 10 0 0 1 0 3.8"></path><path d="M3.721 6.391a10 10 0 0 1 2.7-2.69"></path><path d="M6.391 20.279a10 10 0 0 1-2.69-2.7"></path></svg>',
  globe:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12a10 10 0 1 0 20 0 10 10 0 1 0-20 0"></path><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"></path><path d="M2 12h20"></path></svg>',
  cpu:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20v2"></path><path d="M12 2v2"></path><path d="M17 20v2"></path><path d="M17 2v2"></path><path d="M2 12h2"></path><path d="M2 17h2"></path><path d="M2 7h2"></path><path d="M20 12h2"></path><path d="M20 17h2"></path><path d="M20 7h2"></path><path d="M7 20v2"></path><path d="M7 2v2"></path><path d="M6 4h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"></path><path d="M9 8h6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"></path></svg>',
  drive:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 16h.01"></path><path d="M2.212 11.577a2 2 0 0 0-.212.896V18a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-5.527a2 2 0 0 0-.212-.896L18.55 5.11A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"></path><path d="M21.946 12.013H2.054"></path><path d="M6 16h.01"></path></svg>',
  alert:
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"></path><path d="M12 9v4"></path><path d="M12 17h.01"></path></svg>'
};

var SIG_TITLE_SIGNED =
  'Publisher signature valid against the key recorded for this publisher. Provenance, not a quality or safety claim.';
var SIG_TITLE_UNSIGNED = 'No publisher signature. Provenance cannot be checked.';

/* The facet selects carry an 'all' sentinel option; an absent/'all' facet
   means no filter on that dimension. The TEXT box carries no sentinel:
   its no-filter set is undefined/null/'' ONLY (pivot §4 row 4 — treating
   'all' as no-filter on free text made a search for the word "all" return
   the whole catalogue). */
function isNoFilter(value) {
  return value === undefined || value === null || value === '' || value === 'all';
}

function isNoTextFilter(value) {
  return value === undefined || value === null || value === '';
}

/* The search predicate (CR-24's dimensions: name, publisher, capability,
   standard version, status, evidence level; CR-58's kind). Selects:
   absent/'all' means no filter. Text: absent/'' means no filter; any other
   string — including 'all' — is a literal query. The UI's initial state
   carries the DEFAULT_QUERY. */
function filterRows(rows, query) {
  query = query || {};
  return (rows || []).filter(function (row) {
    if (!isNoFilter(query.kind) && row.kind !== query.kind) return false;
    if (!isNoFilter(query.signature_state) && row.signature_state !== query.signature_state) {
      return false;
    }
    if (!isNoFilter(query.publisher) && row.publisher !== query.publisher) return false;
    if (!isNoFilter(query.standard_version)) {
      var compat = row.compatibility || {};
      var families = (compat.stg_versions || []).concat(compat.otdp_versions || []);
      if (families.indexOf(query.standard_version) === -1) return false;
    }
    /* Evidence facet (#224 follow-on §2.2): include-if-any — a row matches
       level L iff ANY evidence entry carries level L, mirroring the
       standard-version facet's include-if-listed semantics. A row with no
       evidence matches no level. Machine values: hardware|simulated|structural. */
    if (!isNoFilter(query.evidence_level)) {
      var hasLevel = (row.evidence || []).some(function (entry) {
        return String(entry.level || '') === query.evidence_level;
      });
      if (!hasLevel) return false;
    }
    if (!isNoFilter(query.maintenance) && row.maintenance !== query.maintenance) return false;
    if (!isNoFilter(query.advisories)) {
      var hasAdvisories = (row.advisories || []).length > 0;
      if (query.advisories === 'present' && !hasAdvisories) return false;
      if (query.advisories === 'none' && hasAdvisories) return false;
    }
    var caps = query.capabilities || [];
    for (var i = 0; i < caps.length; i++) {
      if (!(row.capabilities && row.capabilities[caps[i]])) return false;
    }
    if (!isNoTextFilter(query.text)) {
      var needle = String(query.text).toLowerCase();
      var haystack = [row.display_name || '', row.package_id || '', row.summary || '']
        .join(' ')
        .toLowerCase();
      if (haystack.indexOf(needle) === -1) return false;
    }
    return true;
  });
}

function markerTexts(markers) {
  return (markers || []).map(function (marker) {
    var id = String(marker);
    return MARKER_DISPLAY[id] || id;
  });
}

/* The display projection for one row (pure): the text/tone payload every
   row cell renders, shared by the static-row matcher and the clone
   renderer (one projection, two consumers — the generator stamps the
   static rows with the same values at deploy time). */
function rowSlots(row) {
  var compat = row.compatibility || {};
  var compatParts = [];
  if ((compat.otdp_versions || []).length) compatParts.push('OTDP ' + compat.otdp_versions.join(', '));
  if ((compat.adapter_api_versions || []).length) {
    compatParts.push('adapter ' + compat.adapter_api_versions.join(', '));
  }
  if ((compat.stg_versions || []).length) compatParts.push('STG ' + compat.stg_versions.join(', '));
  var maintenance = String(row.maintenance || 'unknown');
  var advisories = row.advisories || [];
  var caps = row.capabilities || {};
  var capLines = [];
  if (caps.network_egress) capLines.push({ icon: 'globe', label: 'Network egress' });
  if (caps.subprocess_or_native_library) {
    capLines.push({ icon: 'cpu', label: 'Subprocess or native library' });
  }
  if (caps.filesystem_writes_beyond_evidence_retention) {
    capLines.push({ icon: 'drive', label: 'Filesystem writes' });
  }
  return {
    'display-name': String(row.display_name || ''),
    'release-line': String(row.package_id || '') + ' · ' + String(row.version || ''),
    publisher: String(row.publisher || ''),
    kind: KIND_DISPLAY[String(row.kind || '')] || String(row.kind || ''),
    markers: markerTexts(row.unverified_markers),
    signature: row.signature_state === 'signed-valid' ? 'signed' : 'unsigned',
    'maintenance-text': MAINTENANCE_DISPLAY[maintenance] || maintenance,
    'maintenance-class': MAINTENANCE_BADGE[maintenance] || 'badge-muted',
    compat: compatParts.join(' · ') || 'none declared',
    evidence: (row.evidence || []).map(function (entry) {
      var result = String(entry.result || 'unknown');
      var tone = result === 'passed' ? 'version' : result === 'partial' ? 'warning' : 'danger';
      return { text: String(entry.level || 'unknown') + ' · ' + result, tone: tone };
    }),
    capabilities: capLines,
    advisoryCount: advisories.length
  };
}

function rowKey(row) {
  return String(row.package_id || '') + '@' + String(row.version || '');
}

/* TWINS of the generator's detail_id / record_url (pinned by the page
   tests): the detail host id slugs the row key (raw keys carry '/' and '@',
   which CSS selectors cannot take unescaped); the record URL is relative
   only (R10). */
function detailId(row) {
  return 'bw-detail-' + rowKey(row).replace(/[^A-Za-z0-9-]/g, '-');
}

function recordUrl(row) {
  return (
    'records/' +
    String(row.registry_id || '') +
    '/' +
    String(row.package_id || '') +
    '/' +
    String(row.version || '') +
    '/index.html'
  );
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    filterRows: filterRows,
    rowSlots: rowSlots,
    markerTexts: markerTexts,
    rowKey: rowKey,
    detailId: detailId,
    recordUrl: recordUrl,
    DEFAULT_QUERY: DEFAULT_QUERY,
    MARKER_DISPLAY: MARKER_DISPLAY,
    KIND_DISPLAY: KIND_DISPLAY,
    MAINTENANCE_DISPLAY: MAINTENANCE_DISPLAY,
    MAINTENANCE_BADGE: MAINTENANCE_BADGE
  };
}

/* ── the DOM wiring (browser only) ─────────────────────────────────────── */
(function () {
  if (typeof document === 'undefined') return;

  var list = document.getElementById('release-rows');
  if (!list) return;
  var captionEl = document.getElementById('catalogue-count');
  var emptyEl = document.getElementById('catalogue-empty');
  var noticeEl = document.getElementById('catalogue-notice');
  var shownEl = document.querySelector('[data-bw-shown]');
  var template = list.querySelector('template[data-bw-template]');
  var rows = [];
  var rowPairs = {}; // rowKey -> {row: <tr>, detail: <tr>}
  var staticKeys = []; // rowKeys in the committed block, in order
  var expandState = {}; // rowKey -> 'open' | 'closed' (collapse without re-fetch)

  function textSlot(tr, slot, text) {
    var el = tr.querySelector('[data-bw-slot="' + slot + '"]');
    if (el) el.textContent = text;
  }

  /* The URL round-trip (§2.2 — the hx-push-url intent): the filter state
     rides q, kind, sig, ev, maint, adv and repeated cap params. */
  function queryForUrl(query) {
    var params = new URLSearchParams();
    if (!isNoTextFilter(query.text)) params.set('q', String(query.text));
    if (!isNoFilter(query.kind)) params.set('kind', query.kind);
    if (!isNoFilter(query.signature_state)) params.set('sig', query.signature_state);
    if (!isNoFilter(query.evidence_level)) params.set('ev', query.evidence_level);
    if (!isNoFilter(query.maintenance)) params.set('maint', query.maintenance);
    if (!isNoFilter(query.advisories)) params.set('adv', query.advisories);
    (query.capabilities || []).forEach(function (cap) {
      params.append('cap', cap);
    });
    var text = params.toString();
    return text ? '?' + text : location.pathname;
  }

  function pushQuery(query) {
    try {
      history.pushState({}, '', queryForUrl(query));
    } catch (err) {
      /* pushState can refuse (file:// origins) — filtering must not die */
    }
  }

  function restoreFromUrl() {
    var params = new URLSearchParams(location.search);
    function setSelect(id, value) {
      var el = document.getElementById(id);
      if (!el || value === null) return;
      for (var i = 0; i < el.options.length; i++) {
        if (el.options[i].value === value) {
          el.value = value;
          return;
        }
      }
    }
    var q = params.get('q');
    var textEl = document.getElementById('q');
    if (textEl && q !== null) textEl.value = q;
    setSelect('kind', params.get('kind'));
    setSelect('sig', params.get('sig'));
    setSelect('ev', params.get('ev'));
    setSelect('maint', params.get('maint'));
    setSelect('adv', params.get('adv'));
    params.getAll('cap').forEach(function (cap) {
      var box = list.ownerDocument.querySelector(
        'input[name="cap"][value="' + cap + '"]'
      );
      if (box) box.checked = true;
    });
  }

  function currentQuery() {
    function value(id) {
      var el = document.getElementById(id);
      return el ? el.value : '';
    }
    var capabilities = [];
    var boxes = document.querySelectorAll('input[name="cap"]');
    Array.prototype.forEach.call(boxes, function (box) {
      if (box.checked) capabilities.push(box.value);
    });
    return {
      text: value('q'),
      kind: value('kind'),
      signature_state: value('sig'),
      evidence_level: value('ev'),
      maintenance: value('maint'),
      advisories: value('adv'),
      capabilities: capabilities
    };
  }

  function sigCellHtml(slots) {
    if (slots.signature === 'signed') {
      return (
        '<span class="sig sig-signed" title="' + SIG_TITLE_SIGNED + '">' +
        ICONS.signature + '<span>Signed</span></span>'
      );
    }
    return (
      '<span class="sig sig-unsigned" title="' + SIG_TITLE_UNSIGNED + '">' +
      ICONS.circleDashed + '<span>Unsigned</span></span>'
    );
  }

  function applySlots(tr, row) {
    var slots = rowSlots(row);
    var sigHost = tr.querySelector('[data-bw-slot="signature"]');
    if (sigHost) sigHost.innerHTML = sigCellHtml(slots);
    var anchor = tr.querySelector('a.release-name');
    if (anchor) {
      var url = recordUrl(row);
      anchor.textContent = slots['display-name'];
      anchor.setAttribute('href', url);
      anchor.setAttribute('hx-get', url);
      anchor.setAttribute('hx-select', '#release-detail');
      anchor.setAttribute('hx-target', '#' + detailId(row));
      anchor.setAttribute('hx-swap', 'innerHTML');
      anchor.setAttribute('hx-push-url', 'true');
    }
    textSlot(tr, 'release-line', slots['release-line']);
    textSlot(tr, 'publisher', slots.publisher);
    textSlot(tr, 'kind', slots.kind);
    textSlot(tr, 'markers', slots.markers.length ? 'Unverified: ' + slots.markers.join('; ') : '');
    textSlot(tr, 'maintenance', slots['maintenance-text']);
    var maintenance = tr.querySelector('[data-bw-slot="maintenance"]');
    if (maintenance) maintenance.className = 'badge ' + slots['maintenance-class'];
    textSlot(tr, 'compat', slots.compat);
    var evidenceHost = tr.querySelector('[data-bw-slot="evidence"]');
    if (evidenceHost) {
      evidenceHost.textContent = '';
      slots.evidence.forEach(function (item) {
        var badge = document.createElement('span');
        badge.className = 'badge badge-' + item.tone;
        badge.textContent = item.text;
        evidenceHost.appendChild(badge);
      });
    }
    var capsHost = tr.querySelector('[data-bw-slot="capabilities"]');
    if (capsHost) {
      capsHost.textContent = '';
      if (!slots.capabilities.length) {
        var muted = document.createElement('span');
        muted.className = 'text-muted';
        muted.textContent = 'None declared';
        capsHost.appendChild(muted);
      } else {
        slots.capabilities.forEach(function (cap) {
          var line = document.createElement('span');
          line.className = 'cap-line';
          line.innerHTML = ICONS[cap.icon];
          var label = document.createElement('span');
          label.textContent = cap.label;
          line.appendChild(label);
          capsHost.appendChild(line);
        });
      }
    }
    var advHost = tr.querySelector('[data-bw-slot="advisories"]');
    if (advHost) {
      advHost.textContent = '';
      if (!slots.advisoryCount) {
        var none = document.createElement('span');
        none.className = 'text-muted';
        none.textContent = 'None';
        advHost.appendChild(none);
      } else {
        var badge = document.createElement('span');
        badge.className = 'badge badge-danger';
        badge.innerHTML = ICONS.alert;
        var noun = slots.advisoryCount === 1 ? 'advisory' : 'advisories';
        badge.appendChild(document.createTextNode(slots.advisoryCount + ' ' + noun));
        advHost.appendChild(badge);
      }
    }
  }

  function pairFor(row) {
    var key = rowKey(row);
    if (rowPairs[key]) return rowPairs[key];
    if (!template) return null;
    var children = template.content.children;
    var tr = children[0].cloneNode(true);
    var detail = children[1].cloneNode(true);
    tr.setAttribute('data-bw-package-id', String(row.package_id || ''));
    var host = detail.querySelector('.bw-detail-host');
    if (host) host.id = detailId(row);
    applySlots(tr, row);
    list.appendChild(tr);
    list.appendChild(detail);
    if (typeof htmx !== 'undefined' && htmx.process) htmx.process(tr);
    rowPairs[key] = { row: tr, detail: detail };
    return rowPairs[key];
  }

  function decorateStatic() {
    var staticRows = list.querySelectorAll('tr.bw-row[data-bw-package-id]');
    var defaults = filterRows(rows, DEFAULT_QUERY);
    Array.prototype.forEach.call(staticRows, function (tr, index) {
      var row = defaults[index];
      if (!row) return;
      var detail = tr.nextElementSibling;
      rowPairs[rowKey(row)] = { row: tr, detail: detail };
      staticKeys.push(rowKey(row));
    });
  }

  function applyFilters(push) {
    var query = currentQuery();
    var matches = filterRows(rows, query);
    var matchKeys = {};
    matches.forEach(function (row) {
      matchKeys[rowKey(row)] = true;
    });
    matches.forEach(function (row) {
      pairFor(row);
    });
    Object.keys(rowPairs).forEach(function (key) {
      var pair = rowPairs[key];
      if (matchKeys[key]) pair.row.removeAttribute('hidden');
      else {
        pair.row.setAttribute('hidden', '');
        pair.detail.setAttribute('hidden', '');
      }
    });
    if (captionEl) {
      captionEl.textContent =
        matches.length + (matches.length === 1 ? ' release. ' : ' releases. ') +
        'Select a name for its provenance, evidence and files.';
    }
    if (shownEl) shownEl.textContent = String(matches.length);
    if (emptyEl) {
      if (matches.length) emptyEl.setAttribute('hidden', '');
      else emptyEl.removeAttribute('hidden');
    }
    if (push) pushQuery(query);
  }

  var filterTimer = null;

  function wire() {
    var form = document.getElementById('filters');
    ['kind', 'sig', 'ev', 'maint', 'adv'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('change', function () { applyFilters(true); });
    });
    var caps = document.querySelectorAll('input[name="cap"]');
    Array.prototype.forEach.call(caps, function (box) {
      box.addEventListener('change', function () { applyFilters(true); });
    });
    var text = document.getElementById('q');
    if (text) {
      text.addEventListener(
        'input',
        function () {
          if (filterTimer) clearTimeout(filterTimer);
          filterTimer = setTimeout(function () { applyFilters(true); }, 250);
        },
        true
      );
    }
    if (form) {
      form.addEventListener('reset', function () {
        setTimeout(function () { applyFilters(true); }, 0);
      });
    }
    /* The drill toggle (§2.5): a second click collapses WITHOUT re-fetch —
       the open content is hidden and restored, htmx fetches once per row. */
    document.addEventListener('htmx:beforeRequest', function (event) {
      var target = event.target;
      if (!target || !target.classList || !target.classList.contains('release-name')) return;
      Object.keys(rowPairs).forEach(function (key) {
        var pair = rowPairs[key];
        if (!pair.row || pair.row.querySelector('a.release-name') !== target) return;
        var host = pair.detail && pair.detail.querySelector('.bw-detail-host');
        var open =
          pair.detail && !pair.detail.hasAttribute('hidden') && host &&
          host.childElementCount > 0;
        if (open) {
          event.preventDefault();
          pair.detail.setAttribute('hidden', '');
          pushQuery(currentQuery());
        }
      });
    });
    document.addEventListener('htmx:afterSwap', function (event) {
      var target = event.target;
      if (!target || !target.classList || !target.classList.contains('bw-detail-host')) return;
      var detail = target.closest('tr.bw-detail-row');
      if (detail) detail.removeAttribute('hidden');
    });
  }

  function wireThemeToggle() {
    var button = document.getElementById('bw-theme-toggle');
    if (!button) return;
    try {
      var stored = localStorage.getItem('bw-theme');
      if (stored === 'light' || stored === 'dark') {
        document.documentElement.setAttribute('data-theme', stored);
      }
    } catch (err) {
      /* storage can be unavailable (privacy modes) — the media default stands */
    }
    button.addEventListener('click', function () {
      var root = document.documentElement;
      var current =
        root.getAttribute('data-theme') ||
        (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
          ? 'dark'
          : 'light');
      var next = current === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try {
        localStorage.setItem('bw-theme', next);
      } catch (err) {
        /* see above */
      }
    });
  }

  function start() {
    wireThemeToggle();
    restoreFromUrl();
    fetch('index.json', { headers: { Accept: 'application/json' } })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (!data || !Array.isArray(data.rows)) throw new Error('index unusable');
        rows = data.rows;
        decorateStatic();
        wire();
        applyFilters(false);
      })
      .catch(function () {
        /* Loud degradation: the committed static rows stand untouched. */
        if (noticeEl) noticeEl.removeAttribute('hidden');
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
