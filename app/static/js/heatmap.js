/**
 * Turning density arrays into colour.
 *
 * The scale runs pale yellow to deep red. Nothing else in the app uses warm
 * colour — floors are white, walls navy, exits green, entrances violet — so
 * anything warm on this canvas means crowding and nothing else. That is worth
 * protecting: a heatmap competing with the palette underneath it is unreadable.
 *
 * Three questions, three modes. They are not interchangeable: a corner that
 * briefly packed and a corridor that stayed packed for a minute are different
 * problems, and a cell everybody walked through calmly is not a problem at all.
 */

/** Stops as [value, r, g, b]. Interpolated between, clamped outside. */
const RAMP = [
  [0.00, 255, 245, 200],
  [0.35, 253, 208, 122],
  [0.60, 244, 146, 62],
  [0.80, 214, 78, 42],
  [1.00, 150, 25, 35],
];

export const MODES = {
  peak: {
    label: 'Worst crowding',
    legend: 'people per m² at the tightest moment',
    array: 'peak_density',
    unit: 'people/m²',
    // Fixed to the cell capacity rather than the observed maximum: densities
    // mean something in absolute terms, and a venue that never got crowded
    // should look calm rather than being rescaled until it looks alarming.
    scale: (density) => density.capacity,
    format: (value) => value.toFixed(2),
  },
  duration: {
    label: 'Time spent crowded',
    legend: 'ticks above the crowding threshold',
    array: 'ticks_above_threshold',
    unit: 'ticks',
    scale: (density) => Math.max(1, ...density.ticks_above_threshold),
    format: (value) => String(Math.round(value)),
  },
  traffic: {
    label: 'Busiest routes',
    legend: 'person-ticks spent in each cell',
    array: 'visits',
    unit: 'person-ticks',
    scale: (density) => Math.max(1, ...density.visits),
    format: (value) => String(Math.round(value)),
  },
};

function rampColour(fraction, alpha) {
  const t = Math.max(0, Math.min(1, fraction));
  let low = RAMP[0];
  let high = RAMP[RAMP.length - 1];
  for (let i = 0; i < RAMP.length - 1; i += 1) {
    if (t >= RAMP[i][0] && t <= RAMP[i + 1][0]) {
      low = RAMP[i];
      high = RAMP[i + 1];
      break;
    }
  }
  const span = high[0] - low[0] || 1;
  const k = (t - low[0]) / span;
  const channel = (i) => Math.round(low[i] + (high[i] - low[i]) * k);
  return `rgba(${channel(1)},${channel(2)},${channel(3)},${alpha})`;
}

/**
 * One colour per cell, or null where there is nothing to show.
 *
 * Alpha rises with the value as well as the hue. A flat alpha makes the low end
 * of the scale a solid wash of pale yellow over the whole floor, which buries
 * the plan; letting quiet cells stay nearly transparent keeps the layout
 * readable underneath and draws the eye to the parts that matter.
 */
export function heatColours(density, mode) {
  const spec = MODES[mode];
  if (!spec || !density) return null;

  const values = density[spec.array];
  const max = spec.scale(density);
  const colours = new Array(values.length).fill(null);

  for (let i = 0; i < values.length; i += 1) {
    const value = values[i];
    if (!value) continue;
    const fraction = value / max;
    colours[i] = rampColour(fraction, 0.25 + 0.6 * Math.min(1, fraction));
  }
  return colours;
}

/** Sample stops for the legend, low to high. */
export function legendStops(density, mode, count = 5) {
  const spec = MODES[mode];
  const max = spec.scale(density);
  return Array.from({ length: count }, (_, i) => {
    const fraction = i / (count - 1);
    return {
      colour: rampColour(fraction, 0.25 + 0.6 * fraction),
      label: spec.format(fraction * max),
    };
  });
}
