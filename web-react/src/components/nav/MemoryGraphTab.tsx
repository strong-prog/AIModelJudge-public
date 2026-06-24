import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { getMemoryGraph } from "@/lib/api";
import type { MemoryGraphData } from "@/types/models";

export function MemoryGraphTab() {
  const svgRef = useRef<SVGSVGElement>(null);
  const [data, setData] = useState<MemoryGraphData | null>(null);

  useEffect(() => {
    getMemoryGraph().then(setData).catch(() => {});
  }, []);

  useEffect(() => {
    if (!data || !svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = 300;
    const height = 300;
    svg.attr("viewBox", `0 0 ${width} ${height}`);

    const nodes = data.nodes ?? [];
    const links = data.links ?? [];

    const simulation = d3
      .forceSimulation(nodes as d3.SimulationNodeDatum[])
      .force(
        "link",
        d3
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .forceLink(links)
          .id((d: any) => d.id)
          .distance(60)
      )
      .force("charge", d3.forceManyBody().strength(-100))
      .force("center", d3.forceCenter(width / 2, height / 2));

    const link = svg
      .append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", "var(--border)")
      .attr("stroke-width", 1);

    const nodeGroup = svg
      .append("g")
      .selectAll("g")
      .data(nodes)
      .join("g");

    nodeGroup
      .append("circle")
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .attr("r", (d: any) => d.size || (d.is_hot ? 6 : 3))
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .attr("fill", (d: any) =>
        d.is_hot ? "var(--danger)" : d.memory_type === "pattern" ? "var(--tool-icon)" : "var(--accent)"
      );

    nodeGroup
      .append("text")
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .text((d: any) => (d.content ?? "").slice(0, 20))
      .attr("font-size", "5px")
      .attr("dy", "1.3em")
      .attr("text-anchor", "middle")
      .attr("fill", "var(--text)");

    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y);
      nodeGroup.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
    };
  }, [data]);

  return (
    <div style={{ width: "100%", height: "100%", minHeight: "200px" }}>
      <svg ref={svgRef} style={{ width: "100%", height: "100%" }} />
    </div>
  );
}
