/** Frame types streamed by POST /api/chat as NDJSON, one object per line. */

export type TableFrame = {
  type: "table";
  columns: string[];
  rows: (string | number | boolean | null)[][];
};

export type ChartSpec = {
  type: "line" | "bar";
  label: string;
  labels: string[];
  values: number[];
};

export type ForecastMeta = {
  sku: string;
  method: string;
  historical: { period: string; value: number }[];
  forecast: { period: string; value: number }[];
  inventory_recommendation: number;
  explanation: string;
};

export type InterpretationMeta = {
  sql?: string;
  row_count?: number;
  columns?: string[];
};

export type Frame =
  | { type: "sql"; sql: string }
  | TableFrame
  | { type: "chart"; chart: ChartSpec }
  | { type: "meta"; forecast?: ForecastMeta; interpretation?: InterpretationMeta }
  | { type: "token"; text: string }
  | { type: "error"; message: string }
  | { type: "done" };

/** One rendered chat turn. Assistant turns may carry a table and a chart. */
export type Turn = {
  role: "user" | "assistant";
  content: string;
  sql?: string;
  table?: TableFrame;
  chart?: ChartSpec;
  forecast?: ForecastMeta;
  interpretation?: InterpretationMeta;
  error?: string;
};

/** Parse an NDJSON byte stream into frames, tolerating split lines. */
export async function* readFrames(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<Frame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    // The final element is an incomplete line; keep it for the next chunk.
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.trim()) yield JSON.parse(line) as Frame;
    }
  }
  if (buffer.trim()) yield JSON.parse(buffer) as Frame;
}
