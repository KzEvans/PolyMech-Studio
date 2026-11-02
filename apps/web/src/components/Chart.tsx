import { useEffect, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";
import type { Data, Layout, Legend, Shape } from "plotly.js";
import { richHtml } from "@/lib/rich";

const Plot = createPlotlyComponent(Plotly);

/** Chart palette (separate from UI colours), measured from the user's thesis figures; mirrors
 * THESIS_PALETTE / THESIS_PALETTE_BY_COUNT in polymech_plotting.spec (DECISIONS 2026-10-27). */
export const PALETTE = ["#104680", "#6DADD1", "#F6B293", "#B72230", "#317CB7", "#DC6D57"];
const PALETTE_BY_COUNT: Record<number, string[]> = {
  1: ["#317CB7"],
  2: ["#317CB7", "#DC6D57"],
  3: ["#104680", "#6DADD1", "#DC6D57"],
  4: ["#104680", "#6DADD1", "#F6B293", "#B72230"],
};
const NAVY_ON_DARK = "#F2F2F4"; // navy is unreadable on the dark background

/** Default colour of series `i` when a chart shows `n` series (same rule as the exported figure). */
export function seriesColor(i: number, n: number, dark = false): string {
  const p = PALETTE_BY_COUNT[n] ?? PALETTE;
  const c = p[i % p.length];
  return dark && c === "#104680" ? NAVY_ON_DARK : c;
}

export type Series = {
  name: string;
  x: (number | null)[];
  y: (number | null)[];
  mode?: "lines" | "markers" | "lines+markers" | "text+markers";
  text?: string[]; // point labels (mode "text+markers"), shown above each point
  dash?: "solid" | "dash" | "dot" | "dashdot";
  yaxis?: "y" | "y2";
  marker?: string; // Plotly symbol name, e.g. circle, circle-open, square, triangle-up, diamond, x
  markerSize?: number; // px
  lineWidth?: number; // px
  yErr?: (number | null)[]; // symmetric error bars (same units as y)
  color?: string;
};

export type ChartLegend = {
  show: boolean;
  position: "best" | "upper left" | "upper right" | "lower left" | "lower right" | "outside";
  frame: boolean;
};

export type ChartProps = {
  series: Series[];
  xTitle: string;
  yTitle: string;
  y2Title?: string;
  logX?: boolean;
  logY?: boolean;
  vlines?: { x: number; label?: string }[];
  vspan?: [number, number];
  height?: number;
  ariaLabel: string;
  legendBelow?: boolean; // many named series (e.g. one per material): legend under the plot
  legend?: ChartLegend;
  xRange?: [number | null, number | null];
  yRange?: [number | null, number | null];
};

const LEGEND_POSITIONS = {
  best: { x: 1, xanchor: "right", y: 1, yanchor: "top" },
  "upper left": { x: 0, xanchor: "left", y: 1, yanchor: "top" },
  "upper right": { x: 1, xanchor: "right", y: 1, yanchor: "top" },
  "lower left": { x: 0, xanchor: "left", y: 0, yanchor: "bottom" },
  "lower right": { x: 1, xanchor: "right", y: 0, yanchor: "bottom" },
  outside: { x: 1.02, xanchor: "left", y: 1, yanchor: "top" },
} satisfies Record<ChartLegend["position"], Partial<Legend>>;

function useThemeName() {
  const [t, setT] = useState(document.documentElement.dataset.theme ?? "light");
  useEffect(() => {
    const obs = new MutationObserver(() => setT(document.documentElement.dataset.theme ?? "light"));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);
  return t;
}

/** Interactive preview of scientific curves. Journal style, no transitions (SPEC §9.2). */
export function Chart({ series, xTitle, yTitle, y2Title, logX, logY, vlines = [], vspan, height = 360, ariaLabel, xRange, yRange, legendBelow, legend }: ChartProps) {
  const theme = useThemeName();
  const css = getComputedStyle(document.documentElement);
  const fg = css.getPropertyValue("--text-primary").trim() || "#1d1d1f";
  const bg = css.getPropertyValue("--bg-content").trim() || "#ffffff";
  const data: Data[] = series.map((s, i) => ({
    type: "scatter",
    name: richHtml(s.name),
    x: s.x,
    y: s.y,
    yaxis: s.yaxis ?? "y",
    mode: s.mode ?? "lines",
    line: { color: s.color ?? seriesColor(i, series.length, theme === "dark"), width: s.lineWidth ?? 1.5, dash: s.dash ?? "solid" },
    marker: { color: s.color ?? seriesColor(i, series.length, theme === "dark"), size: s.markerSize ?? 6, symbol: s.marker ?? "circle" },
    ...(s.yErr ? { error_y: { type: "data" as const, array: s.yErr as number[], visible: true, thickness: 1, width: 3 } } : {}),
    ...(s.text ? { text: s.text.map(richHtml), textposition: "top center" as const, textfont: { size: 11 } } : {}),
    hovertemplate: s.text ? "%{text}<br>%{x:.4g}, %{y:.4g}<extra>%{fullData.name}</extra>" : "%{x:.4g}, %{y:.4g}<extra>%{fullData.name}</extra>",
  }));
  // Plotly log axes take log10(range); a null end keeps autorange on that side
  const range = (r: [number | null, number | null] | undefined, log?: boolean) =>
    r && (r[0] !== null || r[1] !== null)
      ? { range: r.map((v) => (v === null ? null : log ? Math.log10(v) : v)), autorange: r[0] === null ? ("min" as const) : r[1] === null ? ("max" as const) : false }
      : {};
  const axis = (title: string, log?: boolean) => ({
    title: { text: richHtml(title), font: { size: 12 } },
    type: (log ? "log" : "linear") as "log" | "linear",
    showline: true,
    mirror: "ticks" as const,
    ticks: "inside" as const,
    linecolor: fg,
    tickcolor: fg,
    showgrid: false,
    zeroline: false,
    automargin: true,
    exponentformat: "power" as const, // never SI letters such as "μ" on scientific axes
    autorange: true as boolean | "min" | "max",
  });
  const shapes: Partial<Shape>[] = vlines.map((v) => ({
    type: "line", xref: "x", yref: "paper", x0: v.x, x1: v.x, y0: 0, y1: 1, line: { color: fg, width: 1, dash: "dash" },
  }));
  if (vspan) {
    shapes.push({ type: "rect", xref: "x", yref: "paper", x0: vspan[0], x1: vspan[1], y0: 0, y1: 1, fillcolor: "rgba(10,100,214,0.10)", line: { width: 0 }, layer: "below" });
  }
  // a new revision whenever the data change, so Plotly re-autoranges after an empty first render
  const revision = series.map((s) => `${s.name}:${s.x.length}:${s.x[0]}:${s.x.at(-1)}:${s.y.at(-1)}`).join("|");
  const legendLayout: Partial<Legend> = legendBelow
    ? { orientation: "h", x: 0, xanchor: "left", y: -0.16, yanchor: "top" }
    : LEGEND_POSITIONS[legend?.position ?? "best"];
  const layout: Partial<Layout> = {
    datarevision: revision,
    height,
    margin: { l: 64, r: y2Title ? 64 : 20, t: 12, b: legendBelow ? 120 : 48 },
    paper_bgcolor: bg,
    plot_bgcolor: bg,
    font: { family: css.getPropertyValue("--ui-font-sans").trim() || "sans-serif", size: 12, color: fg },
    xaxis: { ...axis(xTitle, logX), ...range(xRange, logX) },
    yaxis: { ...axis(yTitle, logY), ...range(yRange, logY) },
    ...(y2Title ? { yaxis2: { ...axis(y2Title), overlaying: "y" as const, side: "right" as const, mirror: false } } : {}),
    showlegend: legend?.show,
    legend: { ...legendLayout, bgcolor: "rgba(0,0,0,0)", bordercolor: fg, borderwidth: legend?.frame ? 1 : 0 },
    shapes,
    transition: { duration: 0, easing: "linear" },
    annotations: vlines.filter((v) => v.label).map((v) => ({ x: v.x, y: 1, xref: "x", yref: "paper", text: v.label, showarrow: false, yanchor: "bottom", font: { size: 11, color: fg } })),
  };
  return (
    // <figure> (not role="img"): the plot contains focusable toolbar buttons
    <figure aria-label={ariaLabel} className="m-0 w-full">
      <Plot
        data={data}
        layout={layout}
        config={{ displaylogo: false, responsive: true, modeBarButtonsToRemove: ["lasso2d", "select2d"], toImageButtonOptions: { format: "svg" } }}
        // explicit height: on resize, responsive Plotly sizes its containers to 100% of this
        // element; without a height it collapses to 0 and the SVG spills over the cards below
        style={{ width: "100%", height }}
        useResizeHandler
      />
    </figure>
  );
}
