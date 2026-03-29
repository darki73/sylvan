export interface SessionStats {
  tool_calls: number;
  duration: string;
  duration_seconds: number;
  symbols_retrieved: number;
  sections_retrieved: number;
  queries: number;
  start_time: string;
  tokens_returned: number;
  tokens_avoided: number;
}

export interface EfficiencyStats {
  total_returned: number;
  total_equivalent: number;
  reduction_percent: number;
  by_category: Record<string, CategoryEfficiency>;
}

export interface CategoryEfficiency {
  calls: number;
  returned: number;
  equivalent: number;
}

export interface CacheStats {
  hits: number;
  misses: number;
  size: number;
  hit_rate: number;
}
