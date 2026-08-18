import type { Cartela } from "@/lib/gateway";

const TOTAL_CARTELAS = 500;
const GRID_SIZE = 25;
const MT_SIZE = 624;
const MT_PERIOD = 397;
const MATRIX_A = 0x9908b0df;
const UPPER_MASK = 0x80000000;
const LOWER_MASK = 0x7fffffff;

/** Python-compatible MT19937 for the integer seed used by game/engine.py. */
class PythonRandom {
  private state = new Uint32Array(MT_SIZE);
  private index = MT_SIZE;

  constructor(seed: number) {
    this.state[0] = 19650218;
    for (let i = 1; i < MT_SIZE; i += 1) {
      const previous = this.state[i - 1] ^ (this.state[i - 1] >>> 30);
      this.state[i] = Math.imul(1812433253, previous) + i;
    }
    // Python's Random(int) uses init_by_array, not init_genrand. For the
    // cartela seeds used by the backend, the seed fits one 32-bit key word.
    let i = 1;
    let j = 0;
    let keyLength = 1;
    for (let k = Math.max(MT_SIZE, keyLength); k > 0; k -= 1) {
      const previous = this.state[i - 1] ^ (this.state[i - 1] >>> 30);
      this.state[i] = (this.state[i] ^ Math.imul(1664525, previous)) + seed + j;
      this.state[i] >>>= 0;
      i += 1;
      j += 1;
      if (i >= MT_SIZE) {
        this.state[0] = this.state[MT_SIZE - 1];
        i = 1;
      }
      if (j >= keyLength) j = 0;
    }
    for (let k = MT_SIZE - 1; k > 0; k -= 1) {
      const previous = this.state[i - 1] ^ (this.state[i - 1] >>> 30);
      this.state[i] = (this.state[i] ^ Math.imul(1566083941, previous)) - i;
      this.state[i] >>>= 0;
      i += 1;
      if (i >= MT_SIZE) {
        this.state[0] = this.state[MT_SIZE - 1];
        i = 1;
      }
    }
    this.state[0] = UPPER_MASK;
  }

  private nextUint32() {
    if (this.index >= MT_SIZE) {
      for (let i = 0; i < MT_SIZE; i += 1) {
        const y = (this.state[i] & UPPER_MASK) | (this.state[(i + 1) % MT_SIZE] & LOWER_MASK);
        this.state[i] = this.state[(i + MT_PERIOD) % MT_SIZE] ^ (y >>> 1) ^ ((y & 1) ? MATRIX_A : 0);
      }
      this.index = 0;
    }
    let y = this.state[this.index++];
    y ^= y >>> 11;
    y ^= (y << 7) & 0x9d2c5680;
    y ^= (y << 15) & 0xefc60000;
    y ^= y >>> 18;
    return y >>> 0;
  }

  private getRandBits(bitCount: number) {
    return this.nextUint32() >>> (32 - bitCount);
  }

  randBelow(limit: number) {
    const bitCount = 32 - Math.clz32(limit);
    let value = this.getRandBits(bitCount);
    while (value >= limit) value = this.getRandBits(bitCount);
    return value;
  }
}

function sampleRange(rng: PythonRandom, start: number, stop: number, count: number) {
  const pool = Array.from({ length: stop - start }, (_, index) => start + index);
  const result: number[] = [];
  for (let index = 0; index < count; index += 1) {
    const offset = rng.randBelow(pool.length - index);
    result.push(pool[offset]);
    pool[offset] = pool[pool.length - index - 1];
  }
  return result;
}

function generateValues(number: number) {
  const rng = new PythonRandom(number * 1337);
  const columns = [
    sampleRange(rng, 1, 16, 5),
    sampleRange(rng, 16, 31, 5),
    sampleRange(rng, 31, 46, 5),
    sampleRange(rng, 46, 61, 5),
    sampleRange(rng, 61, 76, 5),
  ];
  const values: number[] = [];
  for (let row = 0; row < 5; row += 1) {
    values.push(columns[0][row], columns[1][row], row === 2 ? 0 : columns[2][row], columns[3][row], columns[4][row]);
  }
  return values;
}

export function normalizeCartelaValues(card: unknown) {
  if (!card || typeof card !== "object") return [];
  const value = card as { cartela?: unknown; data?: unknown; grid?: unknown };
  const source = value.cartela ?? value.data ?? value.grid;
  const values = Array.isArray(source) && Array.isArray(source[0])
    ? (source as unknown[]).flatMap((row) => Array.isArray(row) ? row : [])
    : Array.isArray(source) ? source : [];
  return values.map(Number).filter((item) => Number.isInteger(item) && item >= 0 && item <= 75).slice(0, GRID_SIZE);
}

export function isValidCartela(card: unknown, expectedNumber?: number) {
  if (!card || typeof card !== "object") return false;
  const number = Number((card as { number?: unknown }).number);
  const values = normalizeCartelaValues(card);
  return Number.isInteger(number) && number >= 1 && number <= TOTAL_CARTELAS
    && (expectedNumber === undefined || number === expectedNumber)
    && values.length === GRID_SIZE
    && values[12] === 0;
}

export function fallbackCartela(number: number): Cartela {
  const safeNumber = Math.max(1, Math.min(TOTAL_CARTELAS, Math.trunc(Number(number) || 1)));
  return { number: safeNumber, cartela: generateValues(safeNumber), status: "fallback" };
}

export function cardValues(card: Cartela | undefined, number?: number) {
  if (isValidCartela(card, number)) return normalizeCartelaValues(card);
  return fallbackCartela(Number(number ?? card?.number ?? 1)).cartela || [];
}
