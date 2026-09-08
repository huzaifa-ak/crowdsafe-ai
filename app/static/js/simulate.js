/**
 * The simulate page.
 *
 * Configure a run, send it, then watch it. The trace comes back with the
 * response, so playback is entirely local once the run has finished — dragging
 * the scrubber costs nothing and never waits on the network.
 */

import { api } from './api.js';
import { GridCanvas } from './canvas.js';
import { Grid } from './grid.js';
import { Player } from './playback.js';
import { MODES, heatColours, legendStops } from './heatmap.js';

const RATES = [1, 2, 4, 8];

class SimulatePage {
  constructor(root) {
    this.root = root;
    this.venueId = Number(root.dataset.venueId);
    this.grid = Grid.from({
      width: Number(root.dataset.width),
      height: Number(root.dataset.height),
      cells: root.dataset.cells,
    });

    this.canvas = new GridCanvas(root.querySelector('#grid-canvas'));
    this.player = null;
    this.running = false;
    this.density = null;
    this.heatMode = 'none';
    this.heat = null;
    this.hover = null;

    this.runButton = root.querySelector('#run');
    this.playButton = root.querySelector('#play');
    this.scrubber = root.querySelector('#scrubber');
    this.rateButton = root.querySelector('#rate');
    this.statusText = root.querySelector('#run-status');
    this.errorList = root.querySelector('#run-errors');
    this.summaryPanel = root.querySelector('#summary');
    this.clock = root.querySelector('#clock');
    this.heatSelect = root.querySelector('#heat-mode');
    this.legend = root.querySelector('#legend');
    this.cellReadout = root.querySelector('#cell-readout');
    this.scorePanel = root.querySelector('#score');

    this.#bindControls();
    window.addEventListener('resize', () => this.#refit());
    this.#refit();
    this.#setPlaybackEnabled(false);
  }

  /* Running ------------------------------------------------------------- */

  #settings() {
    const value = (id) => this.root.querySelector(`#${id}`).value;
    return {
      num_agents: Number(value('num-agents')),
      speed: Number(value('speed')),
      cell_capacity: Number(value('cell-capacity')),
      seed: Number(value('seed')),
      routing: value('routing'),
      reroute: this.root.querySelector('#reroute').checked,
    };
  }

  async run() {
    if (this.running) return;
    this.running = true;
    this.runButton.disabled = true;
    this.#showErrors([]);
    this.#setStatus('Running…');

    try {
      const result = await api.runSimulation(this.venueId, this.#settings());
      this.#showResult(result);
    } catch (error) {
      this.#setStatus(error.message);
      this.#showErrors(error.details || []);
      this.#setPlaybackEnabled(false);
    } finally {
      this.running = false;
      this.runButton.disabled = false;
    }
  }

  #showResult(result) {
    const summary = result.summary;
    this.summary = summary;
    this.density = result.density
      ? { ...result.density, capacity: this.#settings().cell_capacity }
      : null;
    this.#applyHeatMode();

    if (this.player) this.player.destroy();
    this.player = new Player(result.trace, () => this.#drawFrame());

    this.scrubber.max = String(this.player.lastTick);
    this.scrubber.value = '0';
    this.#setPlaybackEnabled(true);
    this.#renderScore(result.assessment, result.metrics);
    this.#renderSummary(summary);
    this.#setStatus(this.#statusFor(summary));
    this.#drawFrame();
    this.player.play();
  }

  #renderScore(assessment, metrics) {
    this.scorePanel.replaceChildren();
    if (!assessment) {
      this.scorePanel.hidden = true;
      return;
    }

    const headline = document.createElement('div');
    headline.className = `score-headline grade-${assessment.grade}`;
    headline.innerHTML =
      `<span class="score-grade">${assessment.grade}</span>` +
      `<span class="score-number numeric">${assessment.score}<small>/100</small></span>`;
    this.scorePanel.append(headline);

    // Every penalty says what caused it. A score nobody can interrogate is a
    // score nobody can act on.
    for (const component of assessment.components) {
      const row = document.createElement('div');
      row.className = 'score-component';

      const bar = document.createElement('div');
      bar.className = 'score-bar';
      const fill = document.createElement('span');
      fill.style.width = `${(component.penalty / component.weight) * 100}%`;
      bar.append(fill);

      const label = document.createElement('div');
      label.className = 'score-label';
      label.innerHTML =
        `<strong>${component.name}</strong>` +
        `<span class="numeric">&minus;${component.penalty}</span>`;

      const detail = document.createElement('p');
      detail.className = 'score-detail';
      detail.textContent = component.detail;

      row.append(label, bar, detail);
      this.scorePanel.append(row);
    }

    for (const reason of assessment.capped_by || []) {
      const note = document.createElement('p');
      note.className = 'score-cap';
      note.textContent = `Capped: ${reason}.`;
      this.scorePanel.append(note);
    }

    if (metrics && metrics.time.binding_constraint) {
      const note = document.createElement('p');
      note.className = 'score-detail';
      note.textContent = metrics.time.binding_constraint === 'doors'
        ? 'The doors are the limit here — a wider exit would help most.'
        : 'Walking distance is the limit here — wider doors would change little.';
      this.scorePanel.append(note);
    }

    this.scorePanel.hidden = false;
  }

  #statusFor(summary) {
    if (summary.status === 'complete') {
      return `Cleared in ${summary.clearing_seconds} s (${summary.clearing_ticks} ticks)`;
    }
    if (summary.status === 'timeout') {
      return `Ran out of time with ${summary.agent_count - summary.evacuated} still inside`;
    }
    return 'Nothing could move — the crowd is stuck';
  }

  #renderSummary(summary) {
    // Clearing time is the headline; the ratio is what makes it mean anything.
    // Twelve seconds is fine in a small room and alarming in a large one, and
    // the ratio is what tells the two apart.
    const rows = [
      ['Clearing time', summary.clearing_seconds ? `${summary.clearing_seconds} s` : '—'],
      ['Against free flow', summary.time_ratio ? `${summary.time_ratio}×` : '—'],
      ['Evacuated', `${summary.evacuated} of ${summary.agent_count}`],
    ];
    if (summary.stranded) rows.push(['Stranded', String(summary.stranded)]);
    if (summary.reroutes) rows.push(['Rerouted', String(summary.reroutes)]);

    const usage = Object.entries(summary.exit_usage);
    for (const [id, count] of usage) {
      const width = summary.exit_widths[id];
      const share = summary.evacuated ? Math.round((count / summary.evacuated) * 100) : 0;
      rows.push([`Exit ${id} (${width} m)`, `${count} people, ${share}%`]);
    }

    this.summaryPanel.replaceChildren();
    for (const [label, value] of rows) {
      const term = document.createElement('dt');
      term.textContent = label;
      const detail = document.createElement('dd');
      detail.className = 'numeric';
      detail.textContent = value;
      this.summaryPanel.append(term, detail);
    }
    this.summaryPanel.hidden = false;
  }

  /* Playback ------------------------------------------------------------ */

  #drawFrame() {
    const player = this.player;
    this.canvas.render(this.grid, {
      agents: player ? player.frame() : [],
      heat: this.heat,
      hover: this.hover,
    });

    if (!player) return;
    this.scrubber.value = String(player.tick);
    this.playButton.textContent = player.playing ? 'Pause' : 'Play';
    this.clock.textContent =
      `${player.seconds.toFixed(1)} s · ${player.remaining} inside`;
  }

  #setPlaybackEnabled(enabled) {
    for (const control of [this.playButton, this.scrubber, this.rateButton]) {
      control.disabled = !enabled;
    }
    if (!enabled) {
      this.clock.textContent = '';
      this.canvas.render(this.grid, {});
    }
  }

  /* Heatmap ------------------------------------------------------------- */

  #applyHeatMode() {
    const mode = this.heatMode;
    this.heat = mode === 'none' ? null : heatColours(this.density, mode);
    this.#renderLegend();
    this.#drawFrame();
  }

  #renderLegend() {
    this.legend.replaceChildren();
    const spec = MODES[this.heatMode];
    if (!spec || !this.density) {
      this.legend.hidden = true;
      return;
    }

    const caption = document.createElement('p');
    caption.className = 'legend-caption';
    caption.textContent = spec.legend;
    this.legend.append(caption);

    const scale = document.createElement('div');
    scale.className = 'legend-scale';
    for (const stop of legendStops(this.density, this.heatMode)) {
      const swatch = document.createElement('span');
      swatch.className = 'legend-stop';
      swatch.style.background = stop.colour;
      swatch.textContent = stop.label;
      scale.append(swatch);
    }
    this.legend.append(scale);
    this.legend.hidden = false;
  }

  #readCell(cell) {
    if (!cell || !this.density || this.heatMode === 'none') {
      this.cellReadout.textContent = '';
      return;
    }
    const spec = MODES[this.heatMode];
    const value = this.density[spec.array][cell.y * this.grid.width + cell.x];
    this.cellReadout.textContent =
      `${cell.x}, ${cell.y} · ${spec.format(value)} ${spec.unit}`;
  }

  #bindControls() {
    this.runButton.addEventListener('click', () => this.run());

    this.heatSelect.addEventListener('change', () => {
      this.heatMode = this.heatSelect.value;
      this.#applyHeatMode();
    });

    const canvasElement = this.canvas.canvas;
    canvasElement.addEventListener('pointermove', (event) => {
      this.hover = this.canvas.cellAt(event, this.grid);
      this.#readCell(this.hover);
      this.#drawFrame();
    });
    canvasElement.addEventListener('pointerleave', () => {
      this.hover = null;
      this.#readCell(null);
      this.#drawFrame();
    });

    this.playButton.addEventListener('click', () => {
      this.player.toggle();
      this.#drawFrame();
    });

    // Dragging the scrubber is a scrub, not a seek-and-resume: nobody wants
    // playback fighting them for the handle.
    this.scrubber.addEventListener('input', () => {
      if (!this.player) return;
      this.player.pause();
      this.player.seek(Number(this.scrubber.value));
      this.#drawFrame();
    });

    this.rateButton.addEventListener('click', () => {
      const next = RATES[(RATES.indexOf(this.player.rate) + 1) % RATES.length];
      this.player.setRate(next);
      this.rateButton.textContent = `${next}×`;
    });

    window.addEventListener('keydown', (event) => {
      if (event.target.matches('input, select, textarea')) return;
      if (!this.player) return;

      if (event.key === ' ') {
        event.preventDefault();
        this.player.toggle();
        this.#drawFrame();
      }
      if (event.key === 'ArrowRight') this.player.step(event.shiftKey ? 10 : 1);
      if (event.key === 'ArrowLeft') this.player.step(event.shiftKey ? -10 : -1);
    });
  }

  #refit() {
    this.canvas.fit(this.grid);
    this.#drawFrame();
  }

  #setStatus(text) {
    this.statusText.textContent = text;
  }

  #showErrors(details) {
    this.errorList.replaceChildren();
    this.errorList.hidden = details.length === 0;
    for (const detail of details) {
      const item = document.createElement('li');
      item.textContent = detail.message;
      this.errorList.append(item);
    }
  }
}

const root = document.querySelector('#simulate');
if (root) new SimulatePage(root);
