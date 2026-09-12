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
 *
 * Each mode has a floor as well as a ceiling. Colouring from zero tints every
 * cell anyone walked through, and a large pale wash reads as danger even when
 * the numbers are mild — the eye sees warm area, not saturation. Starting the
 * ramp at a value that actually means something keeps the warmth honest.
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
    // Half the crowding threshold. Below this people are walking freely and
    // there is nothing to report.
    floor: (density) => density.threshold / 2,
    marker: (density) => density.threshold,
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
    // Any time at all over the threshold is worth showing here; that is what
    // this array already measures.
    floor: () => 1,
    scale: (density) => Math.max(1, ...density.ticks_above_threshold),
    format: (value) => String(Math.round(value)),
  },
  traffic: {
    label: 'Busiest routes',
    legend: 'person-ticks spent in each cell',
    array: 'visits',
    unit: 'person-ticks',
    // A twentieth of the busiest cell. Below that is incidental footfall.
    floor: (density) => Math.max(1, ...density.visits) / 20,
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
  const floor = spec.floor(density);
  const span = Math.max(max - floor, 1e-6);
  const colours = new Array(values.length).fill(null);

  for (let i = 0; i < values.length; i += 1) {
    const value = values[i];
    if (!value || value < floor) continue;
    const fraction = (value - floor) / span;
    colours[i] = rampColour(fraction, 0.3 + 0.6 * Math.min(1, fraction));
  }
  return colours;
}

/** Sample stops for the legend, low to high. */
export function legendStops(density, mode, count = 5) {
  const spec = MODES[mode];
  const max = spec.scale(density);
  const floor = spec.floor(density);
  const marker = spec.marker ? spec.marker(density) : null;

  return Array.from({ length: count }, (_, i) => {
    const fraction = i / (count - 1);
    const value = floor + fraction * (max - floor);
    const next = floor + ((i + 1) / (count - 1)) * (max - floor);
    return {
      colour: rampColour(fraction, 0.3 + 0.6 * fraction),
      label: spec.format(value),
      // Flags the band containing the crowding threshold, so the legend says
      // where "busy" becomes "too busy" rather than leaving it to be guessed.
      isThreshold: marker !== null && value <= marker && marker < next,
    };
  });
}

/** Everything below the floor is not drawn; worth saying so under the scale. */
export function legendFloorNote(density, mode) {
  const spec = MODES[mode];
  return `below ${spec.format(spec.floor(density))} ${spec.unit} not shown`;
}
