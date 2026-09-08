/**
 * Playback.
 *
 * Owns one thing: which tick of the trace is currently showing, and how that
 * advances over real time. It knows nothing about canvases or the DOM — it
 * calls back with a tick index and whoever wired it up decides what to draw.
 *
 * Time is driven by requestAnimationFrame with an accumulator rather than by
 * setInterval on the tick length. A 0.7 s interval would judder against the
 * display's refresh, and at 8x it would be a 87 ms timer that the browser
 * throttles the moment the tab loses focus.
 */

const SECONDS_PER_TICK = 0.7;

export class Player {
  /**
   * @param {number[][]} trace one flat coordinate list per tick
   * @param {(tick: number) => void} onFrame called whenever the shown tick changes
   */
  constructor(trace, onFrame) {
    this.trace = trace;
    this.onFrame = onFrame;
    this.tick = 0;
    this.rate = 4;            // multiples of real time
    this.playing = false;
    this._accumulator = 0;
    this._lastFrame = 0;
    this._frameHandle = null;
  }

  get lastTick() {
    return Math.max(0, this.trace.length - 1);
  }

  get atEnd() {
    return this.tick >= this.lastTick;
  }

  /** Simulated seconds elapsed at the tick currently showing. */
  get seconds() {
    return this.tick * SECONDS_PER_TICK;
  }

  /** People still inside at the tick currently showing. */
  get remaining() {
    return (this.trace[this.tick] || []).length / 2;
  }

  frame() {
    return this.trace[this.tick] || [];
  }

  play() {
    if (this.playing || !this.trace.length) return;
    // Pressing play at the end starts again rather than doing nothing.
    if (this.atEnd) this.tick = 0;
    this.playing = true;
    this._accumulator = 0;
    this._lastFrame = performance.now();
    this._frameHandle = requestAnimationFrame(this.#advance);
  }

  pause() {
    this.playing = false;
    if (this._frameHandle) cancelAnimationFrame(this._frameHandle);
    this._frameHandle = null;
  }

  toggle() {
    this.playing ? this.pause() : this.play();
  }

  seek(tick) {
    const clamped = Math.max(0, Math.min(this.lastTick, Math.round(tick)));
    if (clamped === this.tick) return;
    this.tick = clamped;
    this.onFrame(this.tick);
  }

  step(delta) {
    this.pause();
    this.seek(this.tick + delta);
  }

  setRate(rate) {
    this.rate = rate;
    this._accumulator = 0;
  }

  destroy() {
    this.pause();
  }

  #advance = (now) => {
    if (!this.playing) return;

    const elapsed = (now - this._lastFrame) / 1000;
    this._lastFrame = now;

    // A tab that was in the background hands back a huge elapsed time. Clamping
    // it means playback resumes where it was rather than jumping to the end.
    this._accumulator += Math.min(elapsed, 0.25);

    const secondsPerFrame = SECONDS_PER_TICK / this.rate;
    let moved = false;
    while (this._accumulator >= secondsPerFrame) {
      this._accumulator -= secondsPerFrame;
      if (this.atEnd) {
        this.pause();
        this.onFrame(this.tick);
        return;
      }
      this.tick += 1;
      moved = true;
    }

    if (moved) this.onFrame(this.tick);
    this._frameHandle = requestAnimationFrame(this.#advance);
  };
}
