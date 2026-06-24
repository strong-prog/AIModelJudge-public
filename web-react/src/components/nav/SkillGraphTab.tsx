import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { getSkillsGraph } from "@/lib/api";
import type { SkillGraphData, SkillNode } from "@/types/models";

interface SkillGraphTabProps {
  onNodeClick?: (node: SkillNode) => void;
}

export function SkillGraphTab({ onNodeClick }: SkillGraphTabProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [data, setData] = useState<SkillGraphData | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; node: SkillNode } | null>(null);

  useEffect(() => {
    getSkillsGraph().then(setData).catch(() => {});
  }, []);

  useEffect(() => {
    if (!data || !svgRef.current) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = 400;
    const height = 400;
    svg.attr("viewBox", `0 0 ${width} ${height}`);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const nodes: any[] = (data.nodes ?? []).map((n) => ({ ...n }));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const links: any[] = (data.edges ?? []).map((e) => ({
      source: e.source,
      target: e.target,
      weight: e.weight,
    }));

    const simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink(links)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .id((d: any) => d.id)
          .distance(80)
      )
      .force("charge", d3.forceManyBody().strength(-150))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(15));

    const link = svg
      .append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", "var(--border)")
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .attr("stroke-width", (d: any) => 0.5 + d.weight * 2);

    const nodeGroup = svg
      .append("g")
      .selectAll("g")
      .data(nodes)
      .join("g")
      .attr("cursor", "pointer")
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .call(d3.drag<any, any>()
        .on("start", (event: d3.D3DragEvent<SVGGElement, any, any>, d: any) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on("drag", (event: d3.D3DragEvent<SVGGElement, any, any>, d: any) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on("end", (event: d3.D3DragEvent<SVGGElement, any, any>, d: any) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        })
      )
      .on("click", (_event: MouseEvent, d: SkillNode) => {
        onNodeClick?.(d);
      })
      .on("mouseenter", (event: MouseEvent, d: SkillNode) => {
        const [mx, my] = d3.pointer(event, svgRef.current);
        setTooltip({ x: mx, y: my, node: d });
      })
      .on("mouseleave", () => {
        setTooltip(null);
      });

    nodeGroup
      .append("circle")
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .attr("r", (d: any) => 4 + (d.hot_score ?? 0) * 8)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .attr("fill", (d: any) =>
        d.is_hot ? "var(--danger)" : "var(--accent)"
      )
      .attr("stroke", "var(--border)")
      .attr("stroke-width", 1);

    nodeGroup
      .append("text")
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .text((d: any) => d.name.slice(0, 14))
      .attr("font-size", "5px")
      .attr("dy", "1.5em")
      .attr("text-anchor", "middle")
      .attr("fill", "var(--text)");

    simulation.on("tick", () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      nodeGroup.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
    };
  }, [data, onNodeClick]);

  return (
    <div style={{ width: "100%", height: "100%", minHeight: "250px", position: "relative" }}>
      <svg ref={svgRef} style={{ width: "100%", height: "100%" }} />
      {tooltip && (
        <div
          style={{
            position: "absolute",
            left: tooltip.x + 10,
            top: tooltip.y - 10,
            background: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
            padding: "6px 8px",
            fontSize: "0.6rem",
            color: "var(--text-bright)",
            pointerEvents: "none",
            zIndex: 100,
            maxWidth: "180px",
            boxShadow: "var(--shadow)",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: "2px" }}>{tooltip.node.name}</div>
          <div>hot: {(tooltip.node.hot_score ?? 0).toFixed(2)}</div>
          <div>calls: {tooltip.node.call_count}</div>
        </div>
      )}
    </div>
  );
}
