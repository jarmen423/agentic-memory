const MASK_64 = (1n << 64n) - 1n;
const MASK_128 = (1n << 128n) - 1n;
const FNV_OFFSET = 0xcbf29ce484222325n;
const FNV_PRIME = 0x100000001b3n;

const normalizePart = (value: bigint | number | string | null | undefined): string => {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "bigint") {
    return value.toString();
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value.toString() : "0";
  }
  return value;
};

const fnv1a64 = (input: string, seed = FNV_OFFSET): bigint => {
  let hash = seed;
  for (const char of input) {
    hash ^= BigInt(char.codePointAt(0) ?? 0);
    hash = (hash * FNV_PRIME) & MASK_64;
  }
  return hash;
};

export const normalizeName = (value: string): string =>
  value.trim().toLowerCase().replace(/\s+/g, " ");

export const normalizePredicate = (value: string): string =>
  value
    .trim()
    .toUpperCase()
    .replace(/[\s-]+/g, "_")
    .replace(/[^A-Z0-9_]/g, "");

export const hashU128 = (...parts: Array<bigint | number | string | null | undefined>): bigint => {
  const normalized = parts.map(normalizePart).join("\u241f");
  const hi = fnv1a64(normalized);
  const lo = fnv1a64([...normalized].reverse().join(""), hi ^ 0x9e3779b97f4a7c15n);
  return ((hi << 64n) | lo) & MASK_128;
};
