/**
 * table-sort.js — lightweight client-side table sorting for CYT-NG
 *
 * Usage: add data-sort="text|number|date" to <th> elements you want sortable.
 * Tables must have a <thead> and <tbody>. Any <th> without data-sort is skipped.
 *
 * Columns with data-sort-value attributes on <td> use that value instead of
 * textContent (useful for timestamps rendered as human-readable text).
 */

(function () {
  'use strict';

  function getCellValue(row, colIndex) {
    const cell = row.cells[colIndex];
    if (!cell) return '';
    // Prefer explicit sort value
    const sv = cell.dataset.sortValue;
    if (sv !== undefined) return sv;
    return cell.textContent.trim();
  }

  function compareValues(a, b, type) {
    if (type === 'number') {
      const na = parseFloat(a.replace(/[^0-9.\-]/g, '')) || 0;
      const nb = parseFloat(b.replace(/[^0-9.\-]/g, '')) || 0;
      return na - nb;
    }
    if (type === 'date') {
      const da = new Date(a).getTime() || 0;
      const db = new Date(b).getTime() || 0;
      return da - db;
    }
    // text — locale-aware, case-insensitive
    return a.localeCompare(b, undefined, { sensitivity: 'base' });
  }

  function sortTable(th, thead, tbody) {
    const ths = Array.from(thead.querySelectorAll('th[data-sort]'));
    const colIndex = Array.from(th.closest('tr').cells).indexOf(th);
    const type = th.dataset.sort;

    // Cycle: none → asc → desc → asc …
    const current = th.dataset.sortDir || '';
    const dir = current === 'asc' ? 'desc' : 'asc';

    // Reset all other headers
    ths.forEach(h => {
      if (h !== th) {
        delete h.dataset.sortDir;
        h.querySelector('.sort-arrow').textContent = '';
      }
    });

    th.dataset.sortDir = dir;
    th.querySelector('.sort-arrow').textContent = dir === 'asc' ? ' ▲' : ' ▼';

    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((ra, rb) => {
      const av = getCellValue(ra, colIndex);
      const bv = getCellValue(rb, colIndex);
      const cmp = compareValues(av, bv, type);
      return dir === 'asc' ? cmp : -cmp;
    });

    rows.forEach(r => tbody.appendChild(r));
  }

  function initTable(table) {
    const thead = table.tHead;
    const tbody = table.tBodies[0];
    if (!thead || !tbody) return;

    thead.querySelectorAll('th[data-sort]').forEach(th => {
      // Add arrow span if not already present
      if (!th.querySelector('.sort-arrow')) {
        const arrow = document.createElement('span');
        arrow.className = 'sort-arrow';
        arrow.style.cssText = 'opacity:0.6;font-size:0.7rem;margin-left:2px;';
        th.appendChild(arrow);
      }
      th.style.cursor = 'pointer';
      th.style.userSelect = 'none';
      th.addEventListener('click', () => sortTable(th, thead, tbody));
    });
  }

  function initAll() {
    document.querySelectorAll('table[data-sortable]').forEach(initTable);
  }

  // Run on DOM ready and after HTMX swaps
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
  document.addEventListener('htmx:afterSwap', initAll);
})();
