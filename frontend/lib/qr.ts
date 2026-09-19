/**
 * A QR code, computed here rather than installed.
 *
 * Why no library: every candidate either drags in a canvas renderer, or hands
 * back an `<img>` whose colours and quiet zone are its own business. What this
 * screen needs is the opposite — the module matrix, so the drawing can be a
 * plain SVG with the contrast and the size a projector demands. The part that
 * is genuinely hard (Reed-Solomon over GF(256), mask selection) is ~200 lines
 * of arithmetic with no runtime surface at all, and it was verified the only
 * way that counts: rendering this matrix to pixels and reading it back with an
 * independent decoder (jsQR), across nine payloads from one byte to 271 — which
 * exercises every version, both block groups and the version-information
 * blocks. A wrong table shows up as an unreadable code on a bench, not in front
 * of a jury.
 *
 * Scope on purpose: byte mode, versions 1-10. That is up to 271 bytes, far
 * past any URL this panel shows, and it keeps the modules big — a version 3
 * code is 29 modules across, which at 380 px is 13 px a module and reads from
 * the back of a room.
 *
 * Pure: no DOM, no `fetch`, no `process.env`. Safe on the server and in the
 * browser.
 */

export type EcLevel = "L" | "M" | "Q" | "H";

export type QrCode = {
  version: number;
  ecLevel: EcLevel;
  /** Modules per side, quiet zone excluded. */
  size: number;
  /** `modules[row][col]`, true where the module is dark. */
  modules: boolean[][];
};

const MAX_VERSION = 10;

/** Data codewords available per version (index 0 = version 1), by EC level. */
const DATA_CODEWORDS: Record<EcLevel, readonly number[]> = {
  L: [19, 34, 55, 80, 108, 136, 156, 194, 232, 274],
  M: [16, 28, 44, 64, 86, 108, 124, 154, 182, 216],
  Q: [13, 22, 34, 48, 62, 76, 88, 110, 132, 154],
  H: [9, 16, 26, 36, 46, 60, 66, 86, 100, 122],
};

/** [EC codewords per block, blocks in group 1, blocks in group 2]. */
const BLOCKS: Record<EcLevel, readonly (readonly [number, number, number])[]> = {
  L: [
    [7, 1, 0], [10, 1, 0], [15, 1, 0], [20, 1, 0], [26, 1, 0],
    [18, 2, 0], [20, 2, 0], [24, 2, 0], [30, 2, 0], [18, 2, 2],
  ],
  M: [
    [10, 1, 0], [16, 1, 0], [26, 1, 0], [18, 2, 0], [24, 2, 0],
    [16, 4, 0], [18, 4, 0], [22, 2, 2], [22, 3, 2], [26, 4, 1],
  ],
  Q: [
    [13, 1, 0], [22, 1, 0], [18, 2, 0], [26, 2, 0], [18, 2, 2],
    [24, 4, 0], [18, 2, 4], [22, 4, 2], [20, 4, 4], [24, 6, 2],
  ],
  H: [
    [17, 1, 0], [28, 1, 0], [22, 2, 0], [16, 4, 0], [22, 2, 2],
    [28, 4, 0], [26, 4, 1], [26, 4, 2], [24, 4, 4], [28, 6, 2],
  ],
};

/** Row/column centres of the alignment patterns, per version. */
const ALIGNMENT: readonly (readonly number[])[] = [
  [], [6, 18], [6, 22], [6, 26], [6, 30],
  [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50],
];

/** The two bits that name the EC level inside the format information. */
const EC_BITS: Record<EcLevel, number> = { L: 1, M: 0, Q: 3, H: 2 };

/**
 * Strongest first. Picking the smallest version and then the strongest level
 * that still fits it buys error tolerance for free: a 41-byte URL is a version
 * 3 code at both L and M, so it may as well be M and survive more glare.
 */
const EC_ORDER: readonly EcLevel[] = ["H", "Q", "M", "L"];

/* --------------------------------------------------------------- GF(256) */

const EXP = new Uint8Array(512);
const LOG = new Uint8Array(256);
{
  let x = 1;
  for (let i = 0; i < 255; i += 1) {
    EXP[i] = x;
    LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d; // the QR primitive polynomial
  }
  for (let i = 255; i < 512; i += 1) EXP[i] = EXP[i - 255];
}

function mul(a: number, b: number): number {
  if (a === 0 || b === 0) return 0;
  return EXP[LOG[a] + LOG[b]];
}

/** The generator polynomial for `degree` error-correction codewords. */
function generator(degree: number): number[] {
  let poly = [1];
  for (let i = 0; i < degree; i += 1) {
    const next = new Array<number>(poly.length + 1).fill(0);
    for (let j = 0; j < poly.length; j += 1) {
      next[j] ^= poly[j];
      next[j + 1] ^= mul(poly[j], EXP[i]);
    }
    poly = next;
  }
  return poly;
}

/** Polynomial division remainder: the EC codewords for one block. */
function errorCorrection(block: number[], count: number): number[] {
  const gen = generator(count);
  const work = block.concat(new Array<number>(count).fill(0));
  for (let i = 0; i < block.length; i += 1) {
    const factor = work[i];
    if (factor === 0) continue;
    for (let j = 0; j < gen.length; j += 1) work[i + j] ^= mul(gen[j], factor);
  }
  return work.slice(block.length);
}

/* ------------------------------------------------------------ the payload */

function capacityBytes(version: number, ecLevel: EcLevel): number {
  const countBits = version < 10 ? 8 : 16;
  return Math.floor((DATA_CODEWORDS[ecLevel][version - 1] * 8 - 4 - countBits) / 8);
}

function chooseFormat(length: number): { version: number; ecLevel: EcLevel } {
  for (let version = 1; version <= MAX_VERSION; version += 1) {
    for (const ecLevel of EC_ORDER) {
      if (length <= capacityBytes(version, ecLevel)) return { version, ecLevel };
    }
  }
  throw new Error(
    `qr: ${length} bytes does not fit in a version ${MAX_VERSION} code (max ${capacityBytes(
      MAX_VERSION,
      "L",
    )})`,
  );
}

function dataCodewords(bytes: Uint8Array, version: number, ecLevel: EcLevel): number[] {
  const capacity = DATA_CODEWORDS[ecLevel][version - 1];
  const bits: number[] = [];
  const push = (value: number, width: number) => {
    for (let i = width - 1; i >= 0; i -= 1) bits.push((value >> i) & 1);
  };

  push(0b0100, 4); // byte mode
  push(bytes.length, version < 10 ? 8 : 16);
  for (const byte of bytes) push(byte, 8);

  const total = capacity * 8;
  for (let i = 0; i < 4 && bits.length < total; i += 1) bits.push(0);
  while (bits.length % 8 !== 0) bits.push(0);

  const words: number[] = [];
  for (let i = 0; i < bits.length; i += 8) {
    let byte = 0;
    for (let j = 0; j < 8; j += 1) byte = (byte << 1) | bits[i + j];
    words.push(byte);
  }
  for (let i = 0; words.length < capacity; i += 1) words.push(i % 2 === 0 ? 0xec : 0x11);
  return words;
}

/** Data and EC codewords, interleaved block by block as the spec orders them. */
function interleave(words: number[], version: number, ecLevel: EcLevel): number[] {
  const [ecPerBlock, group1, group2] = BLOCKS[ecLevel][version - 1];
  const blockCount = group1 + group2;
  const shortSize = Math.floor(DATA_CODEWORDS[ecLevel][version - 1] / blockCount);

  const data: number[][] = [];
  const ec: number[][] = [];
  let at = 0;
  for (let b = 0; b < blockCount; b += 1) {
    const size = b < group1 ? shortSize : shortSize + 1;
    const block = words.slice(at, at + size);
    at += size;
    data.push(block);
    ec.push(errorCorrection(block, ecPerBlock));
  }

  const out: number[] = [];
  for (let i = 0; i <= shortSize; i += 1) {
    for (const block of data) if (i < block.length) out.push(block[i]);
  }
  for (let i = 0; i < ecPerBlock; i += 1) {
    for (const block of ec) out.push(block[i]);
  }
  return out;
}

/* ------------------------------------------------------------- the matrix */

type Grid = (boolean | null)[][];

/** BCH(15,5) for the format information, and BCH(18,6) for the version. */
function bchDigit(value: number): number {
  let digit = 0;
  let rest = value;
  while (rest !== 0) {
    digit += 1;
    rest >>>= 1;
  }
  return digit;
}

function bch(data: number, shift: number, poly: number, mask: number): number {
  let rest = data << shift;
  while (bchDigit(rest) - bchDigit(poly) >= 0) {
    rest ^= poly << (bchDigit(rest) - bchDigit(poly));
  }
  return ((data << shift) | rest) ^ mask;
}

const G15 = 0b101_0011_0111;
const G15_MASK = 0b101_0100_0001_0010;
const G18 = 0b1_1111_0010_0101;

function blank(size: number): Grid {
  return Array.from({ length: size }, () => new Array<boolean | null>(size).fill(null));
}

/** The three corners, plus the white separator that frames each of them. */
function placeFinders(grid: Grid, size: number): void {
  for (const [row0, col0] of [
    [0, 0],
    [size - 7, 0],
    [0, size - 7],
  ]) {
    for (let r = -1; r <= 7; r += 1) {
      for (let c = -1; c <= 7; c += 1) {
        const row = row0 + r;
        const col = col0 + c;
        if (row < 0 || row >= size || col < 0 || col >= size) continue;
        const ring =
          (r >= 0 && r <= 6 && (c === 0 || c === 6)) ||
          (c >= 0 && c <= 6 && (r === 0 || r === 6));
        const core = r >= 2 && r <= 4 && c >= 2 && c <= 4;
        grid[row][col] = ring || core;
      }
    }
  }
}

/**
 * Alignment patterns go in before the timing lines on purpose: the only ones
 * to skip are those swallowed by a finder, and "is this cell already taken"
 * is the cheapest test for that — but only while the timing rows are still
 * empty, or the centre one on row 6 would be skipped by mistake.
 */
function placeAlignment(grid: Grid, version: number): void {
  const centres = ALIGNMENT[version - 1];
  for (const row0 of centres) {
    for (const col0 of centres) {
      if (grid[row0][col0] !== null) continue;
      for (let r = -2; r <= 2; r += 1) {
        for (let c = -2; c <= 2; c += 1) {
          grid[row0 + r][col0 + c] = Math.max(Math.abs(r), Math.abs(c)) !== 1;
        }
      }
    }
  }
}

function placeTiming(grid: Grid, size: number): void {
  for (let i = 8; i < size - 8; i += 1) {
    const dark = i % 2 === 0;
    if (grid[6][i] === null) grid[6][i] = dark;
    if (grid[i][6] === null) grid[i][6] = dark;
  }
}

function placeFormat(grid: Grid, size: number, ecLevel: EcLevel, mask: number): void {
  const bits = bch((EC_BITS[ecLevel] << 3) | mask, 10, G15, G15_MASK);
  for (let i = 0; i < 15; i += 1) {
    const dark = ((bits >> i) & 1) === 1;
    if (i < 6) grid[i][8] = dark;
    else if (i < 8) grid[i + 1][8] = dark;
    else grid[size - 15 + i][8] = dark;

    if (i < 8) grid[8][size - i - 1] = dark;
    else if (i < 9) grid[8][15 - i] = dark;
    else grid[8][14 - i] = dark;
  }
  grid[size - 8][8] = true; // the one module that is always dark
}

function placeVersion(grid: Grid, size: number, version: number): void {
  if (version < 7) return;
  const bits = bch(version, 12, G18, 0);
  for (let i = 0; i < 18; i += 1) {
    const dark = ((bits >> i) & 1) === 1;
    grid[Math.floor(i / 3)][(i % 3) + size - 11] = dark;
    grid[(i % 3) + size - 11][Math.floor(i / 3)] = dark;
  }
}

function masked(mask: number, row: number, col: number): boolean {
  switch (mask) {
    case 0:
      return (row + col) % 2 === 0;
    case 1:
      return row % 2 === 0;
    case 2:
      return col % 3 === 0;
    case 3:
      return (row + col) % 3 === 0;
    case 4:
      return (Math.floor(row / 2) + Math.floor(col / 3)) % 2 === 0;
    case 5:
      return ((row * col) % 2) + ((row * col) % 3) === 0;
    case 6:
      return (((row * col) % 2) + ((row * col) % 3)) % 2 === 0;
    default:
      return (((row + col) % 2) + ((row * col) % 3)) % 2 === 0;
  }
}

/** The zigzag: two columns at a time, right to left, skipping the timing column. */
function placeData(grid: Grid, size: number, codewords: number[], mask: number): void {
  let bitIndex = 7;
  let byteIndex = 0;
  let row = size - 1;
  let up = true;

  for (let col = size - 1; col > 0; col -= 2) {
    if (col === 6) col -= 1;
    for (;;) {
      for (let c = 0; c < 2; c += 1) {
        if (grid[row][col - c] !== null) continue;
        let dark = false;
        if (byteIndex < codewords.length) {
          dark = ((codewords[byteIndex] >>> bitIndex) & 1) === 1;
        }
        if (masked(mask, row, col - c)) dark = !dark;
        grid[row][col - c] = dark;
        bitIndex -= 1;
        if (bitIndex === -1) {
          byteIndex += 1;
          bitIndex = 7;
        }
      }
      row += up ? -1 : 1;
      if (row < 0 || row >= size) {
        row -= up ? -1 : 1;
        up = !up;
        break;
      }
    }
  }
}

/** The four penalty rules. Lower is better; the winning mask is the quietest. */
function penalty(modules: boolean[][], size: number): number {
  let score = 0;

  // Rule 1: runs of five or more of the same colour.
  for (let i = 0; i < size; i += 1) {
    for (const byRow of [true, false]) {
      let run = 1;
      for (let j = 1; j < size; j += 1) {
        const previous = byRow ? modules[i][j - 1] : modules[j - 1][i];
        const current = byRow ? modules[i][j] : modules[j][i];
        if (current === previous) {
          run += 1;
          continue;
        }
        if (run >= 5) score += 3 + (run - 5);
        run = 1;
      }
      if (run >= 5) score += 3 + (run - 5);
    }
  }

  // Rule 2: solid 2x2 blocks.
  for (let r = 0; r < size - 1; r += 1) {
    for (let c = 0; c < size - 1; c += 1) {
      const first = modules[r][c];
      if (
        modules[r][c + 1] === first &&
        modules[r + 1][c] === first &&
        modules[r + 1][c + 1] === first
      ) {
        score += 3;
      }
    }
  }

  // Rule 3: the finder-lookalike, in either direction.
  const needle = [true, false, true, true, true, false, true, false, false, false, false];
  const reversed = needle.slice().reverse();
  const matches = (get: (k: number) => boolean, at: number, pattern: boolean[]) =>
    pattern.every((want, k) => get(at + k) === want);
  for (let i = 0; i < size; i += 1) {
    for (let j = 0; j + needle.length <= size; j += 1) {
      const row = (k: number) => modules[i][k];
      const col = (k: number) => modules[k][i];
      if (matches(row, j, needle) || matches(row, j, reversed)) score += 40;
      if (matches(col, j, needle) || matches(col, j, reversed)) score += 40;
    }
  }

  // Rule 4: how far the dark/light balance drifts from half and half.
  let dark = 0;
  for (let r = 0; r < size; r += 1) {
    for (let c = 0; c < size; c += 1) if (modules[r][c]) dark += 1;
  }
  const percent = (dark * 100) / (size * size);
  score += Math.floor(Math.abs(percent - 50) / 5) * 10;

  return score;
}

function render(
  base: Grid,
  size: number,
  version: number,
  ecLevel: EcLevel,
  codewords: number[],
  mask: number,
): boolean[][] {
  const grid = base.map((row) => row.slice());
  placeFormat(grid, size, ecLevel, mask);
  placeVersion(grid, size, version);
  placeData(grid, size, codewords, mask);
  return grid.map((row) => row.map((cell) => cell === true));
}

/* ---------------------------------------------------------------- the API */

/**
 * Encode `text` as a QR code, choosing the smallest version that holds it and
 * the strongest error correction that fits in that version.
 */
export function encodeQr(text: string): QrCode {
  const bytes = new TextEncoder().encode(text);
  const { version, ecLevel } = chooseFormat(bytes.length);
  const size = version * 4 + 17;
  const codewords = interleave(dataCodewords(bytes, version, ecLevel), version, ecLevel);

  const base = blank(size);
  placeFinders(base, size);
  placeAlignment(base, version);
  placeTiming(base, size);

  let modules: boolean[][] | null = null;
  let best = Number.POSITIVE_INFINITY;
  for (let mask = 0; mask < 8; mask += 1) {
    const candidate = render(base, size, version, ecLevel, codewords, mask);
    const score = penalty(candidate, size);
    if (score < best) {
      best = score;
      modules = candidate;
    }
  }

  return { version, ecLevel, size, modules: modules as boolean[][] };
}

/**
 * The dark modules as one SVG path, in a viewBox one unit per module.
 *
 * Horizontal runs become a single sub-path instead of one rect per module:
 * fewer nodes, and no hairline seams between neighbours when the code is blown
 * up on a projector.
 */
export function qrPath(code: QrCode): string {
  const parts: string[] = [];
  for (let row = 0; row < code.size; row += 1) {
    let col = 0;
    while (col < code.size) {
      if (!code.modules[row][col]) {
        col += 1;
        continue;
      }
      let run = 1;
      while (col + run < code.size && code.modules[row][col + run]) run += 1;
      parts.push(`M${col} ${row}h${run}v1h-${run}z`);
      col += run;
    }
  }
  return parts.join("");
}
