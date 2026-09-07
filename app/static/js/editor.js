/**
 * The editor.
 *
 * Owns the grid, the current tool, and the undo history. The grid is immutable,
 * so history is just an array of previous grids — no snapshotting logic, no
 * risk of an entry mutating after it was recorded.
 *
 * Saving sends the whole venue — name, dimensions and the cell string — because
 * the API replaces a venue wholesale. There is no partial update to get wrong.
 */

import { CELL, CELL_COLORS, CELL_NAMES, Grid, linePoints, rectanglePoints } from './grid.js';
import { GridCanvas } from './canvas.js';
import { api } from './api.js';

const HISTORY_LIMIT = 60;

const TOOLS = {
  BRUSH: 'brush',
  RECTANGLE: 'rectangle',
};

class Editor {
  constructor(root) {
    this.root = root;
    this.canvas = new GridCanvas(root.querySelector('#grid-canvas'));

    const width = Number(root.dataset.width) || 30;
    const height = Number(root.dataset.height) || 20;
    this.grid = root.dataset.cells
      ? Grid.from({ width, height, cells: root.dataset.cells })
      : Grid.blank(width, height);

    this.tool = TOOLS.BRUSH;
    this.code = CELL.WALL;

    this.past = [];
    this.future = [];

    /* Set while a pointer is down. `origin` anchors a rectangle; `last` lets a
     * brush stroke interpolate between pointer events. */
    this.stroke = null;
    this.hover = null;

    /* null until the first successful save, which is what decides POST vs PUT. */
    this.venueId = root.dataset.venueId ? Number(root.dataset.venueId) : null;
    this.dirty = false;
    this.saving = false;

    this.#bindPalette();
    this.#bindTools();
    this.#bindCanvas();
    this.#bindHistory();
    this.#bindSize();
    this.#bindSave();

    window.addEventListener('resize', () => this.#refit());
    this.#refit();
  }

  /* Editing ------------------------------------------------------------- */

  /** Replace the grid and record the old one, unless nothing changed. */
  commit(next) {
    if (next === this.grid) return;
    this.past.push(this.grid);
    if (this.past.length > HISTORY_LIMIT) this.past.shift();
    this.future.length = 0;
    this.grid = next;
    this.#afterChange();
  }

  undo() {
    if (!this.past.length) return;
    this.future.push(this.grid);
    this.grid = this.past.pop();
    this.#afterChange();
  }

  redo() {
    if (!this.future.length) return;
    this.past.push(this.grid);
    this.grid = this.future.pop();
    this.#afterChange();
  }

  /* Rendering ----------------------------------------------------------- */

  draw() {
    this.canvas.render(this.grid, {
      hover: this.stroke ? null : this.hover,
      preview: this.#previewCells(),
      previewColor: CELL_COLORS[this.code],
    });
  }

  #previewCells() {
    if (!this.stroke || this.tool !== TOOLS.RECTANGLE || !this.stroke.current) return [];
    const { origin, current } = this.stroke;
    return rectanglePoints(origin.x, origin.y, current.x, current.y);
  }

  #refit() {
    this.canvas.fit(this.grid);
    this.draw();
  }

  #afterChange() {
    this.#markDirty();
    this.#updateCounts();
    this.#updateHistoryButtons();
    this.draw();
  }

  /* Saving -------------------------------------------------------------- */

  #bindSave() {
    this.nameInput = this.root.querySelector('#venue-name');
    this.saveButton = this.root.querySelector('#save');
    this.statusText = this.root.querySelector('#save-status');
    this.errorList = this.root.querySelector('#save-errors');

    this.saveButton.addEventListener('click', () => this.save());
    this.nameInput.addEventListener('input', () => this.#markDirty());

    window.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        this.save();
      }
    });

    /* The browser shows its own wording here; all we control is whether to ask.
     * Only ever ask when there is genuinely unsaved work. */
    window.addEventListener('beforeunload', (event) => {
      if (!this.dirty) return;
      event.preventDefault();
      event.returnValue = '';
    });

    this.#setStatus(this.venueId ? 'Saved' : 'Not saved yet');
  }

  async save() {
    if (this.saving) return;

    const name = this.nameInput.value.trim();
    const venue = {
      name,
      width: this.grid.width,
      height: this.grid.height,
      cells: this.grid.toJSON().cells,
    };

    this.saving = true;
    this.saveButton.disabled = true;
    this.#setStatus('Saving…');
    this.#showErrors([]);

    try {
      const saved = this.venueId
        ? await api.updateVenue(this.venueId, venue)
        : await api.createVenue(venue);

      const isNew = this.venueId === null;
      this.venueId = saved.id;
      this.nameInput.value = saved.name;
      this.dirty = false;
      this.#setStatus('Saved');

      /* Move the address to the venue's own URL so a refresh reopens what was
       * just saved instead of dropping the person on a blank plan. */
      if (isNew) window.history.replaceState({}, '', `/editor/${saved.id}`);
    } catch (error) {
      this.#setStatus(error.message);
      this.#showErrors(error.details || []);
      this.nameInput.classList.toggle('field-invalid', error.forField
        ? error.forField('name').length > 0
        : false);
    } finally {
      this.saving = false;
      this.saveButton.disabled = false;
    }
  }

  #markDirty() {
    if (this.dirty) return;
    this.dirty = true;
    this.#setStatus('Unsaved changes');
  }

  #setStatus(text) {
    if (this.statusText) this.statusText.textContent = text;
  }

  #showErrors(details) {
    if (!this.errorList) return;
    this.errorList.replaceChildren();
    this.errorList.hidden = details.length === 0;
    if (!details.length) this.nameInput.classList.remove('field-invalid');
    for (const detail of details) {
      const item = document.createElement('li');
      item.textContent = detail.message;
      this.errorList.append(item);
    }
  }

  /* Wiring -------------------------------------------------------------- */

  #bindPalette() {
    this.paletteButtons = [...this.root.querySelectorAll('[data-cell]')];
    for (const button of this.paletteButtons) {
      button.addEventListener('click', () => this.#selectCode(button.dataset.cell));
    }
    this.#selectCode(this.code);
  }

  #selectCode(code) {
    this.code = code;
    for (const button of this.paletteButtons) {
      button.setAttribute('aria-pressed', String(button.dataset.cell === code));
    }
    this.draw();
  }

  #bindTools() {
    this.toolButtons = [...this.root.querySelectorAll('[data-tool]')];
    for (const button of this.toolButtons) {
      button.addEventListener('click', () => this.#selectTool(button.dataset.tool));
    }
    this.#selectTool(this.tool);
  }

  #selectTool(tool) {
    this.tool = tool;
    for (const button of this.toolButtons) {
      button.setAttribute('aria-pressed', String(button.dataset.tool === tool));
    }
  }

  #bindCanvas() {
    const element = this.canvas.canvas;

    element.addEventListener('pointerdown', (event) => {
      const cell = this.canvas.cellAt(event, this.grid);
      if (!cell) return;
      element.setPointerCapture(event.pointerId);
      /* `before` is the grid as it was when the stroke started, so the whole
       * stroke collapses into one undo entry however many cells it covers. */
      this.stroke = { origin: cell, current: cell, before: this.grid };

      if (this.tool === TOOLS.BRUSH) {
        this.grid = this.grid.set(cell.x, cell.y, this.code);
      }
      this.draw();
    });

    element.addEventListener('pointermove', (event) => {
      const cell = this.canvas.cellAt(event, this.grid);
      this.hover = cell;

      if (!this.stroke) {
        this.#updateReadout(cell);
        this.draw();
        return;
      }
      if (!cell) return;

      if (this.tool === TOOLS.BRUSH) {
        /* Interpolate: pointer events are far coarser than the movement. */
        const from = this.stroke.current;
        const points = linePoints(from.x, from.y, cell.x, cell.y);
        this.grid = this.grid.setMany(points, this.code);
      }
      this.stroke.current = cell;
      this.#updateReadout(cell);
      this.draw();
    });

    const finish = () => {
      if (!this.stroke) return;
      const { origin, current, before } = this.stroke;
      const tool = this.tool;
      this.stroke = null;

      if (tool === TOOLS.RECTANGLE && current) {
        const points = rectanglePoints(origin.x, origin.y, current.x, current.y);
        this.commit(before.setMany(points, this.code));
        return;
      }

      /* The brush painted onto this.grid live so the stroke was visible. Rewind
       * to `before` and commit the result once, as a single history entry. */
      const painted = this.grid;
      this.grid = before;
      this.commit(painted);
    };

    element.addEventListener('pointerup', finish);
    element.addEventListener('pointercancel', finish);
    element.addEventListener('pointerleave', () => {
      this.hover = null;
      this.#updateReadout(null);
      this.draw();
    });

    /* Right-click paints floor: the fastest way to correct a mistake without
     * leaving the tool you're using. */
    element.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      const cell = this.canvas.cellAt(event, this.grid);
      if (cell) this.commit(this.grid.set(cell.x, cell.y, CELL.FLOOR));
    });
  }

  #bindHistory() {
    this.undoButton = this.root.querySelector('#undo');
    this.redoButton = this.root.querySelector('#redo');
    this.undoButton.addEventListener('click', () => this.undo());
    this.redoButton.addEventListener('click', () => this.redo());

    window.addEventListener('keydown', (event) => {
      if (event.target.matches('input, textarea')) return;

      const modifier = event.ctrlKey || event.metaKey;
      if (modifier && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        if (event.shiftKey) this.redo();
        else this.undo();
        return;
      }
      if (modifier && event.key.toLowerCase() === 'y') {
        event.preventDefault();
        this.redo();
        return;
      }

      /* Number keys pick a cell type, in palette order. */
      const index = Number(event.key) - 1;
      const button = this.paletteButtons[index];
      if (!modifier && button) this.#selectCode(button.dataset.cell);

      if (event.key === 'b') this.#selectTool(TOOLS.BRUSH);
      if (event.key === 'r') this.#selectTool(TOOLS.RECTANGLE);
    });

    this.#updateHistoryButtons();
  }

  #updateHistoryButtons() {
    this.undoButton.disabled = this.past.length === 0;
    this.redoButton.disabled = this.future.length === 0;
  }

  #bindSize() {
    this.widthInput = this.root.querySelector('#venue-width');
    this.heightInput = this.root.querySelector('#venue-height');
    this.widthInput.value = this.grid.width;
    this.heightInput.value = this.grid.height;

    const apply = () => {
      const width = clamp(Number(this.widthInput.value), 5, 80);
      const height = clamp(Number(this.heightInput.value), 5, 60);
      this.widthInput.value = width;
      this.heightInput.value = height;
      const next = this.grid.resize(width, height);
      if (next === this.grid) return;
      this.commit(next);
      this.#refit();
    };

    this.widthInput.addEventListener('change', apply);
    this.heightInput.addEventListener('change', apply);

    this.#updateCounts();
  }

  #updateCounts() {
    const counts = this.grid.counts();
    for (const [code, name] of Object.entries(CELL_NAMES)) {
      const output = this.root.querySelector(`[data-count="${code}"]`);
      if (output) output.textContent = counts[code];
      void name;
    }
    const area = this.root.querySelector('#venue-area');
    if (area) area.textContent = `${this.grid.width} × ${this.grid.height} m`;
  }

  #updateReadout(cell) {
    const readout = this.root.querySelector('#cursor-readout');
    if (!readout) return;
    readout.textContent = cell
      ? `${cell.x}, ${cell.y} · ${CELL_NAMES[this.grid.get(cell.x, cell.y)]}`
      : '';
  }
}

function clamp(value, low, high) {
  if (Number.isNaN(value)) return low;
  return Math.min(high, Math.max(low, Math.round(value)));
}

const root = document.querySelector('#editor');
if (root) new Editor(root);
