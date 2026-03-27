export type RunningStats = {
  n: number;
  meanTUs: number;
  m2TUs: number;
  segmentCount: number;
  lastSegmentStartUs: bigint;
  latestObservationUs: bigint;
};

export const updateRunningStats = (
  current: RunningStats | null,
  observationUs: bigint,
): RunningStats => {
  const value = Number(observationUs);
  if (!current || current.n === 0) {
    return {
      n: 1,
      meanTUs: value,
      m2TUs: 0,
      segmentCount: 1,
      lastSegmentStartUs: observationUs,
      latestObservationUs: observationUs,
    };
  }

  const n = current.n + 1;
  const delta = value - current.meanTUs;
  const meanTUs = current.meanTUs + delta / n;
  const delta2 = value - meanTUs;

  return {
    n,
    meanTUs,
    m2TUs: current.m2TUs + delta * delta2,
    segmentCount: current.segmentCount,
    lastSegmentStartUs: current.lastSegmentStartUs,
    latestObservationUs: observationUs,
  };
};

export const variance = (stats: Pick<RunningStats, "n" | "m2TUs">): number =>
  stats.n < 2 ? 0 : stats.m2TUs / (stats.n - 1);

export const computeMdlLiteScore = (
  stats: Pick<RunningStats, "n" | "m2TUs">,
  complexityPenalty = 1,
): number => {
  if (stats.n === 0) {
    return 0;
  }
  return complexityPenalty * Math.log(stats.n + 1) + (stats.n / 2) * Math.log(variance(stats) + 1e-9);
};

export const decayRelevance = (
  relevance: number,
  lastReinforcedAtUs: bigint,
  nowUs: bigint,
  halfLifeHours = 24 * 7,
): number => {
  if (relevance <= 0) {
    return 0;
  }
  const elapsedHours = Number(nowUs - lastReinforcedAtUs) / 3_600_000_000;
  const decay = Math.pow(2, -elapsedHours / Math.max(halfLifeHours, 0.001));
  return Math.max(0, Math.min(1, relevance * decay));
};
