const HOURS_TO_MICROS = 3_600_000_000;

export const timestampToMicros = (
  value: bigint | number | string | Date | undefined | null,
): bigint => {
  if (value === undefined || value === null) {
    return 0n;
  }
  if (typeof value === "bigint") {
    return value;
  }
  if (typeof value === "number") {
    return BigInt(Math.trunc(value));
  }
  if (value instanceof Date) {
    return BigInt(value.getTime()) * 1000n;
  }
  return BigInt(Date.parse(value)) * 1000n;
};

export const midpointMicros = (startUs: bigint, endUs?: bigint): bigint =>
  endUs === undefined ? startUs : startUs + (endUs - startUs) / 2n;

export const overlaps = (
  startAUs: bigint,
  endAUs: bigint | undefined,
  startBUs: bigint,
  endBUs: bigint | undefined,
): boolean => {
  const resolvedEndA = endAUs ?? 9_223_372_036_854_775_807n;
  const resolvedEndB = endBUs ?? 9_223_372_036_854_775_807n;
  return startAUs <= resolvedEndB && startBUs <= resolvedEndA;
};

export const temporalDistanceMicros = (
  queryUs: bigint,
  startUs: bigint,
  endUs?: bigint,
): number => {
  if (queryUs < startUs) {
    return Number(startUs - queryUs);
  }
  if (endUs !== undefined && queryUs > endUs) {
    return Number(queryUs - endUs);
  }
  return 0;
};

export const isActiveAt = (queryUs: bigint, startUs: bigint, endUs?: bigint): boolean =>
  temporalDistanceMicros(queryUs, startUs, endUs) === 0;

export const halfLifeHoursToMicros = (halfLifeHours: number): number =>
  Math.max(halfLifeHours, 0.001) * HOURS_TO_MICROS;
