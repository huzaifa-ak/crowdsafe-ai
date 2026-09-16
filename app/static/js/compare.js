/**
 * The compare page.
 *
 * Two runs, two plans, and the difference between them. Each run carries its
 * own venue snapshot, so a comparison keeps showing the two layouts it was made
 * from even after both have been edited since.
 */

import { api } from './api.js';
import { GridCanvas } from './canvas.js';
import { Grid } from './grid.js';
import { heatColours } from './heatmap.js';

class ComparePage {
  constructor(root) {
    this.root = root;
    this.baselineSelect = root.querySelector('#baseline');
    this.variantSelect = root.querySelector('#variant');
    this.compareButton = root.querySelector('#compare');
    this.statusText = root.querySelector('#compare-status');
    this.warningsPanel = root.querySelector('#warnings');
    this.verdictPanel = root.querySelector('#verdict');
    this.tableBody = root.querySelector('#changes tbody');
    this.findingsPanel = root.querySelector('#finding-changes');

    this.canvases = {
      baseline: new GridCanvas(root.querySelector('#baseline-canvas')),
      variant: new GridCanvas(root.querySelector('#variant-canvas')),
    };
    this.runs = { baseline: null, variant: null };

    this.compareButton.addEventListener('click', () => this.run());
    window.addEventListener('resize', () => this.#redraw());

    const preset = new URLSearchParams(window.location.search);
    if (preset.get('baseline')) this.baselineSelect.value = preset.get('baseline');
    if (preset.get('variant')) this.variantSelect.value = preset.get('variant');
    if (this.baselineSelect.value && this.variantSelect.value) this.run();
  }

  async run() {
    const baseline = Number(this.baselineSelect.value);
    const variant = Number(this.variantSelect.value);
    if (!baseline || !variant) return;

    this.compareButton.disabled = true;
    this.#setStatus('Comparing…');

    try {
      // The plans are drawn from the runs themselves; the comparison endpoint
      // returns only the difference.
      const [before, after, comparison] = await Promise.all([
        api.getSimulation(baseline, { trace: false }),
        api.getSimulation(variant, { trace: false }),
        api.createComparison(baseline, variant),
      ]);

      this.runs = { baseline: before, variant: after };
      this.#renderPlans();
      this.#renderComparison(comparison.summary);
      this.#setStatus('');
    } catch (error) {
      this.#setStatus(error.message);
    } finally {
      this.compareButton.disabled = false;
    }
  }

  /* Plans ---------------------------------------------------------------- */

  #renderPlans() {
    for (const side of ['baseline', 'variant']) {
      const run = this.runs[side];
      const snapshot = run.venue_snapshot;
      const grid = Grid.from(snapshot);
      const density = run.density
        ? { ...run.density, capacity: run.config.cell_capacity }
        : null;

      this.root.querySelector(`#${side}-caption`).textContent =
        `${run.summary.clearing_seconds ?? '—'} s · ` +
        `${run.assessment.score} (${run.assessment.grade})`;

      this.canvases[side].fit(grid);
      this.canvases[side].render(grid, {
        heat: density ? heatColours(density, 'peak') : null,
      });
      this[`${side}Grid`] = grid;
      this[`${side}Density`] = density;
    }
  }

  #redraw() {
    for (const side of ['baseline', 'variant']) {
      const grid = this[`${side}Grid`];
      if (!grid) continue;
      this.canvases[side].fit(grid);
      this.canvases[side].render(grid, {
        heat: this[`${side}Density`]
          ? heatColours(this[`${side}Density`], 'peak') : null,
      });
    }
  }

  /* Difference ----------------------------------------------------------- */

  #renderComparison(summary) {
    this.verdictPanel.textContent = summary.verdict;
    this.verdictPanel.className =
      `verdict ${summary.comparable ? 'is-comparable' : 'is-not-comparable'}`;
    this.verdictPanel.hidden = false;

    // A table of deltas presented without this caveat looks like evidence when
    // it is not, so the warnings sit above the numbers rather than below them.
    this.warningsPanel.replaceChildren();
    this.warningsPanel.hidden = !summary.warnings.length;
    for (const warning of summary.warnings) {
      const item = document.createElement('li');
      item.textContent = warning.message;
      this.warningsPanel.append(item);
    }

    this.tableBody.replaceChildren();
    for (const row of summary.changes) {
      const tr = document.createElement('tr');
      tr.innerHTML =
        `<td>${row.name}</td>` +
        `<td class="numeric">${format(row.baseline, row.unit)}</td>` +
        `<td class="numeric">${format(row.variant, row.unit)}</td>` +
        `<td class="numeric ${direction(row)}">${delta(row)}</td>`;
      this.tableBody.append(tr);
    }

    this.#renderFindingChanges(summary.findings);
  }

  #renderFindingChanges(findings) {
    this.findingsPanel.replaceChildren();
    const groups = [
      ['Gone', findings.resolved.map((f) => f.label), 'good'],
      ['New', findings.new.map((f) => f.label), 'bad'],
      ['Still there', findings.remaining.map(
        (f) => `${f.label}${f.improved ? ' (eased)' : ' (worse)'}`), 'neutral'],
    ];

    for (const [title, labels, tone] of groups) {
      if (!labels.length) continue;
      const block = document.createElement('div');
      block.className = `finding-change tone-${tone}`;
      const heading = document.createElement('p');
      heading.className = 'finding-change-title';
      heading.textContent = title;
      const list = document.createElement('ul');
      for (const label of labels) {
        const item = document.createElement('li');
        item.textContent = label;
        list.append(item);
      }
      block.append(heading, list);
      this.findingsPanel.append(block);
    }
    this.findingsPanel.hidden = !this.findingsPanel.childElementCount;
  }

  #setStatus(text) {
    this.statusText.textContent = text;
  }
}

function format(value, unit) {
  if (value === null || value === undefined) return '—';
  return unit ? `${value} ${unit}` : String(value);
}

function delta(row) {
  if (row.delta === null || row.delta === 0) return '—';
  const sign = row.delta > 0 ? '+' : '';
  const percent = row.percent !== null ? ` (${row.percent > 0 ? '+' : ''}${row.percent}%)` : '';
  return `${sign}${row.delta}${percent}`;
}

function direction(row) {
  if (row.better === null || row.delta === 0) return '';
  return row.better ? 'is-better' : 'is-worse';
}

const root = document.querySelector('#compare-page');
if (root) new ComparePage(root);
