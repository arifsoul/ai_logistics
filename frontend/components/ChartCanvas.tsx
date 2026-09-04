"use client";

import { useEffect, useRef } from "react";
import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  Filler,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
} from "chart.js";

import type { ChartSpec } from "@/lib/frames";

// Register only what the two chart types need, so the bundle stays small.
Chart.register(
  BarController,
  BarElement,
  CategoryScale,
  Filler,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
);

const GRID = "#1e293b";
const TICK = "#94a3b8";

export type Series = { label: string; values: number[]; color: string };

/** Canvas chart. Pass either a ChartSpec or explicit multi-series data. */
export default function ChartCanvas({
  spec,
  labels,
  series,
  type = "bar",
  className = "h-64",
}: {
  spec?: ChartSpec;
  labels?: string[];
  series?: Series[];
  type?: "line" | "bar";
  className?: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);

  // Props are fresh arrays on every render, so serialize them: the effect then
  // has one primitive dependency and re-creates the chart only on real change.
  const dataKey = JSON.stringify({
    chartType: spec?.type ?? type,
    chartLabels: spec?.labels ?? labels ?? [],
    chartSeries:
      series ??
      (spec
        ? [{ label: spec.label, values: spec.values, color: "#22d3ee" }]
        : []),
  });

  useEffect(() => {
    if (!canvas.current) return;
    const { chartType, chartLabels, chartSeries } = JSON.parse(dataKey) as {
      chartType: "line" | "bar";
      chartLabels: string[];
      chartSeries: Series[];
    };
    const chart = new Chart(canvas.current, {
      type: chartType,
      data: {
        labels: chartLabels,
        datasets: chartSeries.map((item) => ({
          label: item.label,
          data: item.values,
          borderColor: item.color,
          backgroundColor: `${item.color}99`,
          borderWidth: 2,
          fill: chartType === "line",
          tension: 0.3,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: TICK } } },
        scales: {
          x: { ticks: { color: TICK }, grid: { color: GRID } },
          y: { ticks: { color: TICK }, grid: { color: GRID }, beginAtZero: true },
        },
      },
    });
    // Chart.js keeps a canvas registry, so an explicit destroy is required or
    // a re-render throws "Canvas is already in use".
    return () => chart.destroy();
  }, [dataKey]);

  return (
    <div className={className}>
      <canvas ref={canvas} />
    </div>
  );
}
