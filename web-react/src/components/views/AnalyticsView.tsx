import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { getAnalyticsTokens, getBenchmarkStats } from "@/lib/api";
import type { TokenAnalytics } from "@/types/models";
import type { BenchmarkStatsResponse } from "@/types/api";

interface AnalyticsViewProps {
  visible: boolean;
}

export function AnalyticsView({ visible }: AnalyticsViewProps) {
  const tokenSvgRef = useRef<SVGSVGElement>(null);
  const latencySvgRef = useRef<SVGSVGElement>(null);
  const successSvgRef = useRef<SVGSVGElement>(null);
  const [data, setData] = useState<TokenAnalytics | null>(null);
  const [bench, setBench] = useState<BenchmarkStatsResponse | null>(null);

  useEffect(() => {
    if (visible) {
      getAnalyticsTokens().then(setData).catch(() => {});
      getBenchmarkStats(14).then(setBench).catch(() => {});
    }
  }, [visible]);

  // Token chart
  useEffect(() => {
    if (!data || !tokenSvgRef.current) return;
    const svg = d3.select(tokenSvgRef.current);
    svg.selectAll("*").remove();

    const margin = { top: 10, right: 10, bottom: 30, left: 50 };
    const width = 600;
    const height = 180;
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;

    const g = svg
      .attr("viewBox", `0 0 ${width} ${height}`)
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    if (data.days.length === 0) {
      g.append("text")
        .attr("x", innerWidth / 2)
        .attr("y", innerHeight / 2)
        .attr("text-anchor", "middle")
        .attr("fill", "var(--muted)")
        .attr("font-size", "10px")
        .text("Нет данных");
      return;
    }

    const x = d3
      .scaleBand()
      .domain(data.days.map((d) => d.day))
      .range([0, innerWidth])
      .padding(0.2);

    const y = d3
      .scaleLinear()
      .domain([0, d3.max(data.days, (d) => d.input_tokens + d.output_tokens) ?? 0])
      .range([innerHeight, 0]);

    g.append("g")
      .attr("transform", `translate(0,${innerHeight})`)
      .call(d3.axisBottom(x).ticks(5))
      .selectAll("text")
      .attr("font-size", "7px")
      .attr("fill", "var(--muted)");

    g.append("g")
      .call(d3.axisLeft(y).ticks(4))
      .selectAll("text")
      .attr("font-size", "7px")
      .attr("fill", "var(--muted)");

    g.selectAll(".bar")
      .data(data.days)
      .join("rect")
      .attr("x", (d) => x(d.day) ?? 0)
      .attr("y", (d) => y(d.input_tokens + d.output_tokens))
      .attr("width", x.bandwidth())
      .attr("height", (d) => innerHeight - y(d.input_tokens + d.output_tokens))
      .attr("fill", "var(--accent)")
      .attr("rx", 2);
  }, [data]);

  // Latency chart (avg response time by day)
  useEffect(() => {
    if (!bench || !latencySvgRef.current) return;
    const svg = d3.select(latencySvgRef.current);
    svg.selectAll("*").remove();

    const margin = { top: 10, right: 10, bottom: 30, left: 50 };
    const width = 600;
    const height = 180;
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;

    const g = svg
      .attr("viewBox", `0 0 ${width} ${height}`)
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    const days = bench.daily.slice(0, 14).reverse();
    if (days.length === 0) {
      g.append("text")
        .attr("x", innerWidth / 2)
        .attr("y", innerHeight / 2)
        .attr("text-anchor", "middle")
        .attr("fill", "var(--muted)")
        .attr("font-size", "10px")
        .text("Нет данных");
      return;
    }

    const x = d3
      .scalePoint()
      .domain(days.map((d) => d.day))
      .range([0, innerWidth])
      .padding(0.5);

    const maxY = d3.max(days, (d) => d.avg_duration_ms) ?? 1000;
    const y = d3.scaleLinear().domain([0, maxY * 1.2]).range([innerHeight, 0]);

    g.append("g")
      .attr("transform", `translate(0,${innerHeight})`)
      .call(d3.axisBottom(x).ticks(5))
      .selectAll("text")
      .attr("font-size", "7px")
      .attr("fill", "var(--muted)");

    g.append("g")
      .call(d3.axisLeft(y).ticks(4))
      .selectAll("text")
      .attr("font-size", "7px")
      .attr("fill", "var(--muted)");

    const line = d3
      .line<BenchmarkStatsResponse["daily"][number]>()
      .x((d) => x(d.day) ?? 0)
      .y((d) => y(d.avg_duration_ms))
      .curve(d3.curveMonotoneX);

    g.append("path")
      .datum(days)
      .attr("fill", "none")
      .attr("stroke", "var(--accent)")
      .attr("stroke-width", 2)
      .attr("d", line);

    g.selectAll(".dot")
      .data(days)
      .join("circle")
      .attr("cx", (d) => x(d.day) ?? 0)
      .attr("cy", (d) => y(d.avg_duration_ms))
      .attr("r", 3)
      .attr("fill", "var(--accent)");
  }, [bench]);

  // Success rate chart
  useEffect(() => {
    if (!bench || !successSvgRef.current) return;
    const svg = d3.select(successSvgRef.current);
    svg.selectAll("*").remove();

    const margin = { top: 10, right: 10, bottom: 30, left: 40 };
    const width = 600;
    const height = 140;
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;

    const g = svg
      .attr("viewBox", `0 0 ${width} ${height}`)
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    const days = bench.daily.slice(0, 14).reverse();
    if (days.length === 0) {
      g.append("text")
        .attr("x", innerWidth / 2)
        .attr("y", innerHeight / 2)
        .attr("text-anchor", "middle")
        .attr("fill", "var(--muted)")
        .attr("font-size", "10px")
        .text("Нет данных");
      return;
    }

    const x = d3
      .scaleBand()
      .domain(days.map((d) => d.day))
      .range([0, innerWidth])
      .padding(0.2);

    const y = d3.scaleLinear().domain([0, 1]).range([innerHeight, 0]);

    g.append("g")
      .attr("transform", `translate(0,${innerHeight})`)
      .call(d3.axisBottom(x).ticks(5))
      .selectAll("text")
      .attr("font-size", "7px")
      .attr("fill", "var(--muted)");

    g.append("g")
      .call(d3.axisLeft(y).ticks(4).tickFormat(d3.format(".0%")))
      .selectAll("text")
      .attr("font-size", "7px")
      .attr("fill", "var(--muted)");

    g.selectAll(".bar")
      .data(days)
      .join("rect")
      .attr("x", (d) => x(d.day) ?? 0)
      .attr("y", (d) => y(d.success_rate))
      .attr("width", x.bandwidth())
      .attr("height", (d) => innerHeight - y(d.success_rate))
      .attr("fill", (d) => (d.success_rate < 0.9 ? "var(--danger, #e74c3c)" : "var(--green, #27ae60)"))
      .attr("rx", 2);
  }, [bench]);

  if (!visible) return null;

  return (
    <div className="analytics-view">
      <div className="analytics-header">
        <span>Аналитика токенов</span>
        {data && (
          <span style={{ fontSize: "0.65rem", color: "var(--muted)" }}>
            {data.days.reduce((s, d) => s + d.input_tokens + d.output_tokens, 0).toLocaleString()} токенов
          </span>
        )}
      </div>
      <svg ref={tokenSvgRef} style={{ width: "100%", height: "160px" }} />

      <div className="analytics-header" style={{ marginTop: "1rem" }}>
        <span>Время ответа (ms)</span>
        {bench && (
          <span style={{ fontSize: "0.65rem", color: "var(--muted)" }}>
            avg {bench.avg_duration_ms}ms / p50 {bench.p50_duration_ms}ms / p95 {bench.p95_duration_ms}ms
          </span>
        )}
      </div>
      <svg ref={latencySvgRef} style={{ width: "100%", height: "160px" }} />

      <div className="analytics-header" style={{ marginTop: "1rem" }}>
        <span>Success Rate</span>
        {bench && (
          <span style={{ fontSize: "0.65rem", color: "var(--muted)" }}>
            {(bench.success_rate * 100).toFixed(1)}%
          </span>
        )}
      </div>
      <svg ref={successSvgRef} style={{ width: "100%", height: "120px" }} />
    </div>
  );
}
