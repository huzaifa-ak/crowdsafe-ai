/**
 * The grid model.
 *
 * A venue is one flat string of digits, row-major, matching what the API
 * stores. Keeping the browser's representation identical to the server's means
 * saving is just sending the string — no serialisation step to get wrong.
 *
 * Codes here must stay in step with app/cells.py.
 */

export const CELL = {
  FLOOR: '0',
  WALL: '1',
  BARRIER: '2',
  ENTRANCE: '3',
  EXIT: '4',
  SPAWN: '5',
  CHECKPOINT: '6',
};

export const CELL_NAMES = {
  [CELL.FLOOR]: 'Floor',
  [CELL.WALL]: 'Wall',
  [CELL.BARRIER]: 'Barrier',
  [CELL.ENTRANCE]: 'Entrance',
  [CELL.EXIT]: 'Exit',
  [CELL.SPAWN]: 'Spawn',
  [CELL.CHECKPOINT]: 'Checkpoint',
};

export const CELL_COLORS = {
  [CELL.FLOOR]: '#ffffff',
  [CELL.WALL]: '#14202b',
  [CELL.BARRIER]: '#9aa6b0',
  [CELL.ENTRANCE]: '#6d4bb0',
  [CELL.EXIT]: '#007a45',
  [CELL.SPAWN]: '#5b6ee1',
  // Teal: cool, so it never competes with the density heatmap, and far
  // enough from both the exit green and the entrance violet to be told apart
  // at a glance.
  [CELL.CHECKPOINT]: '#0e7c86',
};

export class Grid {
  constructor(width, height, cells) {
    if (cells.length !== width * height) {
      throw new Error(
        `Expected ${width * height} cells for ${width}x${height}, got ${cells.length}`,
      );
    }
    this.width = width;
    this.height = height;
    this.cells = cells;
  }

  /** A room: walls around the outside, floor within. */
  static blank(width, height) {
    let cells = '';
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const onEdge = x === 0 || y === 0 || x === width - 1 || y === height - 1;
        cells += onEdge ? CELL.WALL : CELL.FLOOR;
      }
    }
    return new Grid(width, height, cells);
  }

  static from({ width, height, cells }) {
    return new Grid(width, height, cells);
  }

  contains(x, y) {
    return x >= 0 && y >= 0 && x < this.width && y < this.height;
  }

  get(x, y) {
    return this.contains(x, y) ? this.cells[y * this.width + x] : undefined;
  }

  /**
   * Paint one cell. Returns a new Grid, or `this` when nothing would change —
   * so callers can cheaply skip repainting and skip pushing history entries.
   */
  set(x, y, code) {
    if (!this.contains(x, y)) return this;
    const index = y * this.width + x;
    if (this.cells[index] === code) return this;
    const cells = this.cells.slice(0, index) + code + this.cells.slice(index + 1);
    return new Grid(this.width, this.height, cells);
  }

  /** Paint many cells in one pass. Coordinates outside the grid are ignored. */
  setMany(points, code) {
    const chars = this.cells.split('');
    let changed = false;
    for (const [x, y] of points) {
      if (!this.contains(x, y)) continue;
      const index = y * this.width + x;
      if (chars[index] === code) continue;
      chars[index] = code;
      changed = true;
    }
    return changed ? new Grid(this.width, this.height, chars.join('')) : this;
  }

  /**
   * Resize, anchored at the top-left. New cells become floor, except on the
   * outer edge where they become wall, so a grown room stays enclosed.
   */
  resize(width, height) {
    if (width === this.width && height === this.height) return this;
    let cells = '';
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const existing = this.get(x, y);
        if (existing !== undefined) {
          cells += existing;
        } else {
          const onEdge = x === 0 || y === 0 || x === width - 1 || y === height - 1;
          cells += onEdge ? CELL.WALL : CELL.FLOOR;
        }
      }
    }
    return new Grid(width, height, cells);
  }

  counts() {
    const result = {};
    for (const code of Object.values(CELL)) result[code] = 0;
    for (const char of this.cells) {
      if (char in result) result[char] += 1;
    }
    return result;
  }

  toJSON() {
    return { width: this.width, height: this.height, cells: this.cells };
  }
}

/** Every cell in the rectangle spanned by two corners, in either direction. */
export function rectanglePoints(x0, y0, x1, y1) {
  const points = [];
  const [left, right] = x0 <= x1 ? [x0, x1] : [x1, x0];
  const [top, bottom] = y0 <= y1 ? [y0, y1] : [y1, y0];
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) points.push([x, y]);
  }
  return points;
}

/**
 * Cells along a straight line between two points (Bresenham).
 *
 * Pointer events fire far more slowly than the mouse moves, so a quick drag
 * reports a handful of scattered positions. Without this the brush leaves
 * dotted trails instead of strokes.
 */
export function linePoints(x0, y0, x1, y1) {
  const points = [];
  let x = x0;
  let y = y0;
  const dx = Math.abs(x1 - x0);
  const dy = -Math.abs(y1 - y0);
  const stepX = x0 < x1 ? 1 : -1;
  const stepY = y0 < y1 ? 1 : -1;
  let error = dx + dy;

  for (;;) {
    points.push([x, y]);
    if (x === x1 && y === y1) break;
    const doubled = 2 * error;
    if (doubled >= dy) {
      error += dy;
      x += stepX;
    }
    if (doubled <= dx) {
      error += dx;
      y += stepY;
    }
  }
  return points;
}
