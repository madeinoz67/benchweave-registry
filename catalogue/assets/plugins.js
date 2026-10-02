/* BenchWeave plugin catalogue search (issue #224 slice 2, registry-hosted
   pivot). Plain JS, no build chain, no dependencies. Two halves:

   1. PURE: filterRows(rows, query) (the search predicate — data in, data
      out, no DOM) and rowSlots(row) (the display projection for one row).
      Both are exported to CommonJS behind a typeof module guard so node can
      require this file and prove them against the hand-derived truth table
      (tests/run_search_spec.mjs) — one line of toolchain-free seam, no
      bundler.
   2. WIRING (browser only): fetch the same-origin generated index.json,
      decorate each committed row's version/compat/digest slots from the row
      data, drive the filter bar, render non-default rows on demand from the
      generated template card, and keep the result count and empty states
      honest. On fetch failure the committed static rows stand untouched and
      a notice appears — loud degradation, never a blank page.

   The default view (CR-22) is admitted releases with a valid signature:
   exactly the rows the generated page's static cards carry. Everything else
   is reachable only through explicit filters, and renders with its kind tag
   (CR-56). This repository carries no website-style version-literal gate
   (the pivot record §6.2: the index legitimately carries version strings;
   the page is a deploy-time artifact) — versions and digests still render
   from the served index at runtime, keeping the no-JS view honest.
*/

/* The two slice-1 unverified markers' display strings — a TWIN of
   scripts/generate_catalogue_page.py MARKER_DISPLAY, pinned byte-equal by
   tests/test_catalogue_page.py. Unknown marker ids render verbatim
   (forward-honest, never dropped). */
var MARKER_DISPLAY = {
  'conformance-evidence-self-attested': 'conformance evidence self-attested',
  'review-is-process-not-proof': 'review is process, not proof'
};

/* (R2, pivot §4) The digest/revision display truncation length — a TWIN of
   scripts/generate_catalogue_page.py TRUNCATE_AT, pinned equal by
   tests/test_catalogue_page.py. One constant, two carriers. */
var TRUNCATE_AT = 12;

var DEFAULT_QUERY = { kind: 'admitted-release', signature_state: 'signed-valid' };

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
   standard version, status; CR-58's kind). Selects: absent/'all' means no
   filter. Text: absent/'' means no filter; any other string — including
   'all' — is a literal query. The UI's initial state carries the
   DEFAULT_QUERY. */
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

function markerSlots(markers) {
  return (markers || []).map(function (marker) {
    var id = String(marker);
    return { text: MARKER_DISPLAY[id] || id, tone: 'warning' };
  });
}

function evidenceSlots(evidence) {
  return (evidence || []).map(function (entry) {
    var level = String(entry.level || 'unknown');
    var result = String(entry.result || 'unknown');
    var tone = result === 'passed' ? 'success' : result === 'partial' ? 'warning' : 'danger';
    return { text: level + ' · ' + result, tone: tone, path: String(entry.report_path || '') };
  });
}

/* The display projection for one row (pure): every card slot's text plus
   the badge tones. Empty collections carry their explicit-none text so a
   clone can render CR-20's "or explicitly none" exactly like the
   generated static card. */
function rowSlots(row) {
  var compat = row.compatibility || {};
  var compatParts = [];
  if ((compat.otdp_versions || []).length) compatParts.push('OTDP ' + compat.otdp_versions.join(', '));
  if ((compat.adapter_api_versions || []).length) {
    compatParts.push('adapter ' + compat.adapter_api_versions.join(', '));
  }
  if ((compat.stg_versions || []).length) compatParts.push('STG ' + compat.stg_versions.join(', '));
  var digest = String(row.manifest_sha256 || '');
  var source = String(row.source_revision || '');
  var maintenance = String(row.maintenance || 'unknown');
  var maintenanceClass = {
    maintained: 'badge-success',
    maintenance_only: 'badge-warning',
    unmaintained: 'badge-danger'
  }[maintenance] || 'badge-version';
  return {
    'display-name': String(row.display_name || ''),
    summary: String(row.summary || ''),
    publisher: String(row.publisher || ''),
    licence: String(row.licence_spdx || ''),
    maintenance: maintenance,
    'maintenance-class': maintenanceClass,
    kind: String(row.kind || ''),
    'release-id': String(row.registry_id || '') + '/' + String(row.package_id || ''),
    version: 'v' + String(row.version || ''),
    digest: digest.slice(0, TRUNCATE_AT) + '…',
    'digest-title': digest,
    compat: compatParts.join(' · '),
    'source-revision': source.slice(0, TRUNCATE_AT) + '…',
    'source-revision-title': source,
    evidence: evidenceSlots(row.evidence),
    'evidence-none': (row.evidence || []).length ? '' : 'no test evidence',
    advisories: (row.advisories || []).map(function (id) {
      return { text: String(id), tone: 'danger' };
    }),
    'advisories-none': (row.advisories || []).length ? '' : 'no advisories',
    markers: markerSlots(row.unverified_markers)
  };
}

/* The exact release directory (runtime-only), pinned to the page's own
   provenance stamp (fold R7): the click-through must show the exact bytes
   this page was generated from, matching the footer's stamp. ref is read
   from the footer's data-bw-stamp at wiring time; the 'main' fallback never
   applies on a rendered page (the generator refuses to build without a
   real sha). */
function releaseDirUrl(row, ref) {
  var base =
    'https://github.com/madeinoz67/benchweave-registry/tree/' + (ref || 'main') + '/releases/' +
    String(row.registry_id || '') +
    '/' +
    String(row.package_id || '');
  return row.version ? base + '/' + String(row.version) : base;
}

function rowKey(row) {
  return String(row.package_id || '') + '@' + String(row.version || '');
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    filterRows: filterRows,
    rowSlots: rowSlots,
    markerSlots: markerSlots,
    releaseDirUrl: releaseDirUrl,
    rowKey: rowKey,
    DEFAULT_QUERY: DEFAULT_QUERY,
    MARKER_DISPLAY: MARKER_DISPLAY
  };
}

/* ── the DOM wiring (browser only) ─────────────────────────────────────── */
(function () {
  if (typeof document === 'undefined') return;

  var list = document.getElementById('catalogue-list');
  if (!list) return;
  var countEl = document.getElementById('catalogue-count');
  var emptyEl = document.getElementById('catalogue-empty');
  var noticeEl = document.getElementById('catalogue-notice');
  var template = list.querySelector('template[data-bw-template]');
  /* R7: the page's own provenance stamp pins every release link's ref —
     what the footer says the page was generated from is what links open. */
  var stampEl = document.querySelector('[data-bw-stamp]');
  var pageRef = stampEl ? stampEl.getAttribute('data-bw-stamp') : 'main';
  var rows = [];
  var cards = {}; // rowKey -> element
  var staticKeys = []; // rowKeys in the committed block, in order

  function textSlot(card, slot, text, title) {
    var el = card.querySelector('[data-bw-slot="' + slot + '"]');
    if (!el) return;
    el.textContent = text;
    if (title) el.setAttribute('title', title);
    if (el.hasAttribute('hidden') && text) el.removeAttribute('hidden');
  }

  function badgeRow(card, slot, items, noneText) {
    var host = card.querySelector('[data-bw-slot="' + slot + '"]');
    if (!host) return;
    host.textContent = '';
    if (!items.length && noneText) {
      var muted = document.createElement('span');
      muted.className = 'text-muted';
      muted.textContent = noneText;
      host.appendChild(muted);
      return;
    }
    items.forEach(function (item) {
      var badge = document.createElement('span');
      badge.className = 'badge badge-' + (item.tone || 'version');
      badge.textContent = item.text;
      host.appendChild(badge);
      if (item.path) {
        var code = document.createElement('code');
        code.textContent = item.path;
        host.appendChild(code);
      }
    });
  }

  function applySlots(card, row) {
    var slots = rowSlots(row);
    textSlot(card, 'display-name', slots['display-name']);
    textSlot(card, 'summary', slots.summary);
    textSlot(card, 'publisher', slots.publisher);
    textSlot(card, 'licence', slots.licence);
    textSlot(card, 'maintenance', slots.maintenance);
    var maintenance = card.querySelector('[data-bw-slot="maintenance"]');
    if (maintenance) maintenance.className = 'badge ' + slots['maintenance-class'];
    textSlot(card, 'kind', slots.kind);
    textSlot(card, 'release-id', slots['release-id']);
    textSlot(card, 'version', slots.version);
    textSlot(card, 'digest', slots.digest, slots['digest-title']);
    textSlot(card, 'compat', slots.compat);
    textSlot(card, 'source-revision', slots['source-revision'], slots['source-revision-title']);
    badgeRow(card, 'evidence', slots.evidence, slots['evidence-none']);
    badgeRow(card, 'advisories', slots.advisories, slots['advisories-none']);
    badgeRow(card, 'markers', slots.markers, '');
    var link = card.querySelector('[data-bw-slot="evidence-link"]');
    if (link) link.setAttribute('href', releaseDirUrl(row, pageRef));
  }

  function decorateStatic() {
    var staticCards = list.querySelectorAll('.spec-card[data-bw-package-id]');
    var defaults = filterRows(rows, DEFAULT_QUERY);
    staticCards.forEach(function (card, index) {
      var row = defaults[index];
      if (!row) return;
      cards[rowKey(row)] = card;
      staticKeys.push(rowKey(row));
      var slots = rowSlots(row);
      textSlot(card, 'version', slots.version);
      textSlot(card, 'digest', slots.digest, slots['digest-title']);
      textSlot(card, 'compat', slots.compat);
      var link = card.querySelector('[data-bw-slot="evidence-link"]');
      if (link) link.setAttribute('href', releaseDirUrl(row, pageRef));
    });
  }

  function cardFor(row) {
    var key = rowKey(row);
    if (cards[key]) return cards[key];
    if (!template) return null;
    var card = template.content.firstElementChild.cloneNode(true);
    card.setAttribute('data-bw-package-id', String(row.package_id || ''));
    applySlots(card, row);
    list.appendChild(card);
    cards[key] = card;
    return card;
  }

  function currentQuery() {
    function value(id) {
      var el = document.getElementById(id);
      return el ? el.value : '';
    }
    var capabilities = [];
    if (document.getElementById('bw-filter-cap-network') &&
        document.getElementById('bw-filter-cap-network').checked) {
      capabilities.push('network_egress');
    }
    if (document.getElementById('bw-filter-cap-subprocess') &&
        document.getElementById('bw-filter-cap-subprocess').checked) {
      capabilities.push('subprocess_or_native_library');
    }
    if (document.getElementById('bw-filter-cap-filesystem') &&
        document.getElementById('bw-filter-cap-filesystem').checked) {
      capabilities.push('filesystem_writes_beyond_evidence_retention');
    }
    return {
      text: value('bw-filter-text'),
      publisher: value('bw-filter-publisher'),
      standard_version: value('bw-filter-standard'),
      signature_state: value('bw-filter-signature'),
      maintenance: value('bw-filter-maintenance'),
      advisories: value('bw-filter-advisories'),
      kind: value('bw-filter-kind'),
      capabilities: capabilities
    };
  }

  function applyFilters() {
    var query = currentQuery();
    var matches = filterRows(rows, query);
    var matchKeys = {};
    matches.forEach(function (row) {
      matchKeys[rowKey(row)] = true;
    });
    matches.forEach(cardFor);
    Object.keys(cards).forEach(function (key) {
      if (matchKeys[key]) cards[key].removeAttribute('hidden');
      else cards[key].setAttribute('hidden', '');
    });
    if (countEl) {
      countEl.textContent = 'Showing ' + matches.length + ' of ' + rows.length + ' releases';
    }
    if (emptyEl) {
      if (matches.length) emptyEl.setAttribute('hidden', '');
      else emptyEl.removeAttribute('hidden');
    }
  }

  function fillSelect(id, options) {
    var select = document.getElementById(id);
    if (!select) return;
    while (select.options.length > 1) select.remove(1);
    options.forEach(function (option) {
      var el = document.createElement('option');
      el.value = option.value;
      el.textContent = option.label;
      select.appendChild(el);
    });
  }

  function buildFacets() {
    var publishers = {};
    var standards = {};
    rows.forEach(function (row) {
      publishers[String(row.publisher || '')] = true;
      var compat = row.compatibility || {};
      (compat.stg_versions || []).forEach(function (v) {
        standards[v] = standards[v] || { stg: false, otdp: false };
        standards[v].stg = true;
      });
      (compat.otdp_versions || []).forEach(function (v) {
        standards[v] = standards[v] || { stg: false, otdp: false };
        standards[v].otdp = true;
      });
    });
    fillSelect(
      'bw-filter-publisher',
      Object.keys(publishers)
        .sort()
        .map(function (name) {
          return { value: name, label: name };
        })
    );
    fillSelect(
      'bw-filter-standard',
      Object.keys(standards)
        .sort()
        .map(function (version) {
          var families = standards[version];
          var label =
            (families.stg && families.otdp ? 'STG · OTDP ' : families.stg ? 'STG ' : 'OTDP ') +
            version;
          return { value: version, label: label };
        })
    );
  }

  function wire() {
    [
      'bw-filter-text',
      'bw-filter-publisher',
      'bw-filter-standard',
      'bw-filter-signature',
      'bw-filter-maintenance',
      'bw-filter-advisories',
      'bw-filter-kind',
      'bw-filter-cap-network',
      'bw-filter-cap-subprocess',
      'bw-filter-cap-filesystem'
    ].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('input', applyFilters);
    });
    applyFilters();
  }

  function start() {
    fetch('index.json', { headers: { Accept: 'application/json' } })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (!data || !Array.isArray(data.rows)) throw new Error('index unusable');
        rows = data.rows;
        decorateStatic();
        buildFacets();
        wire();
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
