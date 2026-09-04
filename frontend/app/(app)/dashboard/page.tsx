"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import ChartCanvas from "@/components/ChartCanvas";
import { api } from "@/lib/api";

type Kpis = {
  total_orders: number;
  delivered_orders: number;
  delayed_orders: number;
  on_time_delivery_rate: number;
  average_delivery_days: number;
};

type QueryResult = { chart: { labels: string[]; values: number[] } };

const COLORS = { cyan: "#22d3ee", amber: "#fbbf24", rose: "#fb7185" };

const queryFor = (metric: string, dimension: string) =>
  api<QueryResult>("/api/analytics/query", {
    method: "POST",
    body: JSON.stringify({ metric, dimension }),
  });

export default function DashboardPage() {
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [volume, setVolume] = useState<QueryResult | null>(null);
  const [delivered, setDelivered] = useState<QueryResult | null>(null);
  const [delayed, setDelayed] = useState<QueryResult | null>(null);
  const [carrier, setCarrier] = useState<QueryResult | null>(null);
  const [region, setRegion] = useState<QueryResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api<Kpis>("/api/analytics/kpis"),
      queryFor("orders", "month"),
      queryFor("delivered_orders", "month"),
      queryFor("delayed_orders", "month"),
      queryFor("delay_rate", "carrier"),
      queryFor("orders", "region"),
    ])
      .then(([kpiData, volumeData, deliveredData, delayedData, carrierData, regionData]) => {
        setKpis(kpiData);
        setVolume(volumeData);
        setDelivered(deliveredData);
        setDelayed(delayedData);
        setCarrier(carrierData);
        setRegion(regionData);
      })
      .catch((caught) =>
        setError(caught instanceof Error ? caught.message : "Could not load"),
      );
  }, []);

  const cards: [string, string][] = kpis
    ? [
        ["Total orders", String(kpis.total_orders)],
        ["Delivered", String(kpis.delivered_orders)],
        ["Delayed", String(kpis.delayed_orders)],
        ["On-time rate", `${kpis.on_time_delivery_rate}%`],
        ["Avg. delivery", `${kpis.average_delivery_days} days`],
      ]
    : [];

  return (
    <main className="mx-auto w-full max-w-7xl space-y-6 px-5 py-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.25em] text-cyan-400">
            Operations intelligence
          </p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">
            Logistics Analytics
          </h1>
          <p className="mt-2 text-slate-400">
            Fixed overview charts. For any specific question, ask in chat.
          </p>
        </div>
        <Link
          href="/chat"
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:border-cyan-400"
        >
          Ask a question in chat
        </Link>
      </header>

      {error && (
        <p role="alert" className="text-rose-400">
          {error}
        </p>
      )}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {cards.map(([label, value]) => (
          <div
            key={label}
            className="rounded-xl border border-slate-800 bg-slate-900 p-5"
          >
            <p className="text-sm text-slate-400">{label}</p>
            <p className="mt-2 text-2xl font-bold text-cyan-300">{value}</p>
          </div>
        ))}
      </section>

      <section className="grid gap-5 lg:grid-cols-2">
        <article className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="font-semibold">Order volume by month</h2>
          {volume && (
            <ChartCanvas
              type="line"
              labels={volume.chart.labels}
              series={[
                { label: "Orders", values: volume.chart.values, color: COLORS.cyan },
              ]}
              className="mt-4 h-64"
            />
          )}
        </article>

        <article className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="font-semibold">Delivery performance</h2>
          {delivered && delayed && (
            <ChartCanvas
              type="bar"
              labels={delivered.chart.labels}
              series={[
                {
                  label: "Delivered",
                  values: delivered.chart.values,
                  color: COLORS.cyan,
                },
                {
                  label: "Delayed",
                  values: delayed.chart.values,
                  color: COLORS.rose,
                },
              ]}
              className="mt-4 h-64"
            />
          )}
        </article>

        <article className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="font-semibold">Delay rate by carrier</h2>
          {carrier && (
            <ChartCanvas
              type="bar"
              labels={carrier.chart.labels}
              series={[
                {
                  label: "Delay rate (%)",
                  values: carrier.chart.values,
                  color: COLORS.amber,
                },
              ]}
              className="mt-4 h-72"
            />
          )}
        </article>

        <article className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="font-semibold">Orders by region</h2>
          {region && (
            <ChartCanvas
              type="bar"
              labels={region.chart.labels}
              series={[
                { label: "Orders", values: region.chart.values, color: COLORS.cyan },
              ]}
              className="mt-4 h-72"
            />
          )}
        </article>
      </section>
    </main>
  );
}
