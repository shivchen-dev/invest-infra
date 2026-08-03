import type { DailyBarResponse } from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { formatDate, formatDecimal } from "../../utils/format";

interface ClosePriceChartProps {
  bars: DailyBarResponse[];
  toNumber: (value: string | number | null | undefined) => number | null;
}

export function ClosePriceChart({ bars, toNumber }: ClosePriceChartProps) {
  const closePrices = bars
    .map((bar) => toNumber(bar.close))
    .filter((value): value is number => value !== null);

  if (closePrices.length < 2) {
    return (
      <EmptyState
        title="无法绘制走势图"
        description="可用收盘价不足两条。"
      />
    );
  }

  const width = 720;
  const height = 200;
  const paddingX = 36;
  const paddingY = 24;
  const innerWidth = width - paddingX * 2;
  const innerHeight = height - paddingY * 2;

  const min = Math.min(...closePrices);
  const max = Math.max(...closePrices);
  const range = max - min || 1;

  const points = closePrices.map((value, index) => {
    const x =
      paddingX + (innerWidth * index) / Math.max(closePrices.length - 1, 1);
    const y =
      paddingY + innerHeight - ((value - min) / range) * innerHeight;
    return { x, y, value };
  });

  const linePath = points
    .map((point, index) =>
      index === 0 ? `M ${point.x} ${point.y}` : `L ${point.x} ${point.y}`,
    )
    .join(" ");

  const fillPath = `${linePath} L ${points[points.length - 1].x} ${
    paddingY + innerHeight
  } L ${points[0].x} ${paddingY + innerHeight} Z`;

  const firstDate = bars[0]?.trade_date ?? "";
  const lastDate = bars[bars.length - 1]?.trade_date ?? "";
  const middleDate =
    bars[Math.floor(bars.length / 2)]?.trade_date ?? "";

  return (
    <figure className="etfDetailChart" aria-label="收盘价走势图">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        preserveAspectRatio="xMidYMid meet"
        className="etfDetailChartSvg"
      >
        <title>收盘价走势图</title>
        <desc>
          {firstDate} 至 {lastDate}，共 {bars.length} 个交易日，最高 {formatDecimal(max)}，
          最低 {formatDecimal(min)}。
        </desc>
        <g className="etfDetailChartGrid">
          {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
            const y = paddingY + innerHeight * (1 - tick);
            return (
              <line
                key={tick}
                x1={paddingX}
                x2={width - paddingX}
                y1={y}
                y2={y}
              />
            );
          })}
        </g>
        <path d={fillPath} className="etfDetailChartArea" />
        <path d={linePath} className="etfDetailChartLine" />
        {points.map((point, index) => (
          <circle
            key={index}
            cx={point.x}
            cy={point.y}
            r={2.5}
            className="etfDetailChartPoint"
          />
        ))}
        <g className="etfDetailChartAxis">
          <text x={paddingX} y={paddingY - 6} textAnchor="start">
            {formatDecimal(max, 4)}
          </text>
          <text
            x={paddingX}
            y={paddingY + innerHeight + 14}
            textAnchor="start"
          >
            {formatDecimal(min, 4)}
          </text>
          <text x={paddingX} y={height - 4} textAnchor="start">
            {formatDate(firstDate)}
          </text>
          {middleDate && (
            <text
              x={paddingX + innerWidth / 2}
              y={height - 4}
              textAnchor="middle"
            >
              {formatDate(middleDate)}
            </text>
          )}
          <text
            x={width - paddingX}
            y={height - 4}
            textAnchor="end"
          >
            {formatDate(lastDate)}
          </text>
        </g>
      </svg>
    </figure>
  );
}
