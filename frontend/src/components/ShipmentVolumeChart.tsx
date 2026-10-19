import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
export default function ShipmentVolumeChart({
  data,
}: {
  data: { name: string; shipments: number; products: number }[];
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data}>
        <defs>
          <linearGradient id="shipments" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#c8f060" stopOpacity={0.15} />
            <stop offset="95%" stopColor="#c8f060" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="products" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#60d0f0" stopOpacity={0.15} />
            <stop offset="95%" stopColor="#60d0f0" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="#ffffff08"
          vertical={false}
        />
        <XAxis
          dataKey="name"
          stroke="#ffffff15"
          fontSize={11}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          stroke="#ffffff15"
          fontSize={11}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#0a0a0a",
            border: "1px solid #ffffff10",
            borderRadius: "16px",
            fontSize: "12px",
            backdropFilter: "blur(20px)",
            boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
          }}
          itemStyle={{ color: "#f0ece4" }}
        />
        <Area
          type="monotone"
          dataKey="shipments"
          stroke="#c8f060"
          strokeWidth={2}
          fill="url(#shipments)"
        />
        <Area
          type="monotone"
          dataKey="products"
          stroke="#60d0f0"
          strokeWidth={2}
          fill="url(#products)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
