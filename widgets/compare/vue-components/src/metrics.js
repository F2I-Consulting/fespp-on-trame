/*
 * The metrics of the matrix: their canonical order, the words a reader sees,
 * the column each is written under in the CSV, and which of them a block draws.
 */

// the canonical metric order: must match engine/compare_matrix._METRIC_KEYS
export const METRIC_KEYS = [
  "Cardinality", "NaN_count", "Minimum", "Maximum", "Mean",
  "Mean (V)", "Mean (PV)", "Mean (L)",
  "Standard Deviation", "Variance", "Sum", "P10", "Q1", "Median", "Q3", "P90",
  "Skewness", "Kurtosis", "M2", "M3", "M4",
];

export const METRIC_LABELS = {
  Total: "Total count",
  Cardinality: "Defined count",
  NaN_count: "Undefined count",
  Minimum: "Min", Maximum: "Max", Mean: "Mean",
  "Mean (V)": "Mean (V)", "Mean (PV)": "Mean (PV)", "Mean (L)": "Mean (L)",
  "Standard Deviation": "Std Dev", Variance: "Variance",
  Sum: "Sum", P10: "P10", Q1: "Q1", Median: "Median", Q3: "Q3", P90: "P90",
  Skewness: "Skewness", Kurtosis: "Kurtosis",
  M2: "M2", M3: "M3", M4: "M4",
};

const PERCENTILE_TITLE = "Percentile of the CELL values: P10 is the value a tenth of the cells are below, P90 the value nine tenths are below — not the reserves convention";

// header tooltips for the metrics whose definition needs words: what a mean
// is weighted by, which convention a percentile follows
export const METRIC_TITLES = {
  Total: "Every value: defined + undefined",
  Cardinality: "The values read: cells with a finite value",
  NaN_count: "The cells without a value",
  P10: PERCENTILE_TITLE,
  P90: PERCENTILE_TITLE,
  Mean: "Arithmetic mean, one cell one vote, in the unit of the property",
  "Mean (V)": "Mean weighted by the cell volume, in the unit of the property",
  "Mean (PV)": "Mean weighted by the cell pore volume (volume × net-to-gross × porosity), in the unit of the property",
  "Mean (L)": "On a blocked wellbore's row: the mean along the hole, each interval weighted by its length, in the unit of the property",
};

export const PRESETS = [
  { label: "Central tendency", title: "Mean, Mean (V), Mean (PV), Mean (L), Median, Q1, Q3",
    keys: ["Mean", "Mean (V)", "Mean (PV)", "Mean (L)", "Median", "Q1", "Q3"] },
  { label: "Percentiles", title: "P10, Q1, Median, Q3, P90 of the cell values",
    keys: ["P10", "Q1", "Median", "Q3", "P90"] },
  { label: "Spread", title: "Min, Max, Std Dev, Variance",
    keys: ["Minimum", "Maximum", "Standard Deviation", "Variance"] },
  { label: "Shape", title: "Skewness, Kurtosis, M2, M3, M4",
    keys: ["Skewness", "Kurtosis", "M2", "M3", "M4"] },
  { label: "All", title: "Every metric", keys: METRIC_KEYS },
];

// the CSV column of each metric (snake case, the unit appended by csvColumn).
// Every key of METRIC_KEYS needs one, or its header comes out as
// "undefined (unit)", or empty in a block without a unit.
export const CSV_METRIC = {
  Cardinality: "value_count", NaN_count: "no_value_count",
  Minimum: "min", Maximum: "max", Mean: "mean",
  "Mean (V)": "mean_volume_weighted", "Mean (PV)": "mean_pore_volume_weighted",
  "Mean (L)": "mean_length_weighted",
  "Standard Deviation": "std_dev", Variance: "variance",
  Sum: "sum", P10: "p10", Q1: "q1", Median: "median", Q3: "q3", P90: "p90",
  Skewness: "skewness", Kurtosis: "kurtosis",
  M2: "m2", M3: "m3", M4: "m4",
};

// the counts: always the first columns of the matrix, whatever "Metrics" shows;
// "Total" is theirs, summed by the matrix
export const COUNT_COLUMNS = ["Total", "Cardinality", "NaN_count"];
export const COUNT_KEYS = new Set(COUNT_COLUMNS);

// the column of the representation a row reads, sorted by its name: the key
// the server sorts it under (engine/compare_matrix.REPRESENTATION)
export const REP_COLUMN = "Representation";

// what a row with no unit says, in the matrix and in the CSV
export const NO_UNIT = "none declared";

/* Whether a block has this metric at all: a Sum means nothing on a fraction or
   a ratio, the mean along the hole exists only on a blocked wellbore's row. */
export function blockHas(block, metric) {
  if (metric === "Sum") return block.sum_meaningful !== false;
  if (metric === "Mean (L)") return !!block.has_length;
  return true;
}

/* Whether a row's figure means anything: a block keeps its Sum for the rows
   where it does, the others write none (their file keeps it, raw). */
export function rowHas(row, metric) {
  return metric !== "Sum" || row.sum_meaningful !== false;
}
