/**
 * Client-side mirror of app/domains/credentials/service.py::generate_password.
 *
 * Used for instant preview while the operator drags the length slider or flips a
 * class checkbox - no network round-trip. The backend endpoint stays the source
 * of truth (same algorithm, same constants); keep the two in sync.
 */

import type { PasswordGenParams } from "../api/credentials";

// no quotes, backslash, space or pipe (shell/TOML/CSV quoting hazards)
export const SYMBOLS = "!@#$%^&*()-_=+[]{};:,.?/";
export const AMBIGUOUS = "Il1O0o5S2Z8B";

const CLASSES: { key: keyof PasswordGenParams; chars: string }[] = [
  { key: "uppercase", chars: "ABCDEFGHIJKLMNOPQRSTUVWXYZ" },
  { key: "lowercase", chars: "abcdefghijklmnopqrstuvwxyz" },
  { key: "digits", chars: "0123456789" },
  { key: "symbols", chars: SYMBOLS },
];

export const DEFAULT_PARAMS: PasswordGenParams = {
  length: 20,
  uppercase: true,
  lowercase: true,
  digits: true,
  symbols: true,
  exclude_ambiguous: false,
  exclude_chars: "",
  min_of_each: true,
};

/** Uniform random index in [0, max) via rejection sampling over Uint32. */
function randInt(max: number): number {
  if (max <= 0) throw new Error("max must be positive");
  const limit = Math.floor(0xffffffff / max) * max;
  const buf = new Uint32Array(1);
  let x = 0;
  do {
    crypto.getRandomValues(buf);
    x = buf[0];
  } while (x >= limit);
  return x % max;
}

function pick(pool: string): string {
  return pool[randInt(pool.length)];
}

function shuffle<T>(arr: T[]): T[] {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = randInt(i + 1);
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

export interface LocalPasswordResult {
  password: string;
  entropyBits: number;
  error: string | null;
}

export function generatePasswordLocal(params: PasswordGenParams): LocalPasswordResult {
  const banned = new Set(params.exclude_chars.split(""));
  if (params.exclude_ambiguous) for (const c of AMBIGUOUS) banned.add(c);

  const pools: string[] = [];
  for (const { key, chars } of CLASSES) {
    if (!params[key]) continue;
    const pool = [...chars].filter((c) => !banned.has(c)).join("");
    if (pool) pools.push(pool);
  }

  if (pools.length === 0) {
    return { password: "", entropyBits: 0, error: "Не осталось ни одного класса символов после исключений" };
  }
  if (params.min_of_each && params.length < pools.length) {
    return {
      password: "",
      entropyBits: 0,
      error: `Длина ${params.length} мала, чтобы включить по символу из ${pools.length} выбранных классов`,
    };
  }

  const combined = pools.join("");
  let chars: string[];
  if (params.min_of_each) {
    chars = pools.map((pool) => pick(pool));
    while (chars.length < params.length) chars.push(pick(combined));
    shuffle(chars);
  } else {
    chars = Array.from({ length: params.length }, () => pick(combined));
  }

  return {
    password: chars.join(""),
    entropyBits: params.length * Math.log2(combined.length),
    error: null,
  };
}

/** Rough label + 0..4 bucket for a strength meter, keyed off total entropy. */
export function strength(entropyBits: number): { label: string; level: 0 | 1 | 2 | 3 | 4 } {
  if (entropyBits < 40) return { label: "Слабый", level: 1 };
  if (entropyBits < 66) return { label: "Средний", level: 2 };
  if (entropyBits < 100) return { label: "Хороший", level: 3 };
  return { label: "Очень сильный", level: 4 };
}
