/**
 * Canvas rendering.
 *
 * Knows how to draw a grid and how to turn a pointer position into a cell. It
 * holds no editing state — the editor owns the grid and asks for a redraw.
 */

import { CELL_COLORS } from './grid.js';

const MIN_CELL_PX = 6;
const MAX_CELL_PX = 28;

/* A heavier rule every five cells. Five metres is the unit people actually
 * reason in when looking at a floor plan — "the bar is about ten metres from
 * the door" — so the grid should make that readable without counting. */
const MAJOR_EVERY = 5;

const LINE_MINOR = '#e8ecee';
const LINE_MAJOR = '#c9d2d8';
const PREVIEW_OUTLINE = '#14202b';

export class GridCanvas {
  constructor(canvas) {
    this.canvas = canvas;
    this.context = canvas.getContext('2d');
    this.cellSize = 16;
    this.originX = 0;
    this.originY = 0;
  }

  /**
   * Size the canvas to its container and work out how big a cell can be.
   * Called on load, on resize, and whenever the grid's dimensions change.
   */
  fit(grid) {
    const box = this.canvas.parentElement.getBoundingClientRect();
    const available = {
      width: Math.max(box.width - 32, 120),
      height: Math.max(box.height - 32, 120),
    };

    const size = Math.floor(
      Math.min(available.width / grid.width, available.height / grid.height),
    );
    this.cellSize = Math.max(MIN_CELL_PX, Math.min(MAX_CELL_PX, size));

    const drawnWidth = this.cellSize * grid.width;
    const drawnHeight = this.cellSize * grid.height;
    this.originX = Math.floor((available.width - drawnWidth) / 2) + 16;
    this.originY = Math.floor((available.height - drawnHeight) / 2) + 16;

    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = Math.floor(box.width * ratio);
    this.canvas.height = Math.floor(box.height * ratio);
    this.canvas.style.width = `${box.width}px`;
    this.canvas.style.height = `${box.height}px`;
    this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  /** Pointer position to cell coordinates. Returns null outside the grid. */
  cellAt(event, grid) {
    const box = this.canvas.getBoundingClientRect();
    const x = Math.floor((event.clientX - box.left - this.originX) / this.cellSize);
    const y = Math.floor((event.clientY - box.top - this.originY) / this.cellSize);
    return grid.contains(x, y) ? { x, y } : null;
  }

  /**
   * @param {Grid} grid
   * @param {object} overlay
   * @param {Array<[number, number]>} overlay.preview cells a pending action would paint
   * @param {string} overlay.previewColor
   * @param {{x: number, y: number}|null} overlay.hover
   */
  render(grid, overlay = {}) {
    const ctx = this.context;
    const size = this.cellSize;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.save();
    ctx.translate(this.originX, this.originY);

    for (let y = 0; y < grid.height; y += 1) {
      for (let x = 0; x < grid.width; x += 1) {
        ctx.fillStyle = CELL_COLORS[grid.get(x, y)] || CELL_COLORS['0'];
        ctx.fillRect(x * size, y * size, size, size);
      }
    }

    this.#drawRules(grid);

    const preview = overlay.preview || [];
    if (preview.length) {
      ctx.globalAlpha = 0.55;
      ctx.fillStyle = overlay.previewColor || PREVIEW_OUTLINE;
      for (const [x, y] of preview) {
        if (grid.contains(x, y)) ctx.fillRect(x * size, y * size, size, size);
      }
      ctx.globalAlpha = 1;
    }

    if (overlay.hover && grid.contains(overlay.hover.x, overlay.hover.y)) {
      ctx.strokeStyle = PREVIEW_OUTLINE;
      ctx.lineWidth = 2;
      ctx.strokeRect(
        overlay.hover.x * size + 1,
        overlay.hover.y * size + 1,
        size - 2,
        size - 2,
      );
    }

    /* The venue's outer boundary, so a grid that doesn't fill the canvas still
     * reads as a plan of something rather than as a floating patch of colour. */
    ctx.strokeStyle = LINE_MAJOR;
    ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, grid.width * size - 1, grid.height * size - 1);

    ctx.restore();
  }

  #drawRules(grid) {
    const ctx = this.context;
    const size = this.cellSize;
    /* Below about ten pixels a cell, minor rules turn the plan into mush. */
    const showMinor = size >= 10;

    ctx.lineWidth = 1;
    for (let x = 0; x <= grid.width; x += 1) {
      const major = x % MAJOR_EVERY === 0;
      if (!major && !showMinor) continue;
      ctx.strokeStyle = major ? LINE_MAJOR : LINE_MINOR;
      ctx.beginPath();
      ctx.moveTo(x * size + 0.5, 0);
      ctx.lineTo(x * size + 0.5, grid.height * size);
      ctx.stroke();
    }
    for (let y = 0; y <= grid.height; y += 1) {
      const major = y % MAJOR_EVERY === 0;
      if (!major && !showMinor) continue;
      ctx.strokeStyle = major ? LINE_MAJOR : LINE_MINOR;
      ctx.beginPath();
      ctx.moveTo(0, y * size + 0.5);
      ctx.lineTo(grid.width * size, y * size + 0.5);
      ctx.stroke();
    }
  }
}
