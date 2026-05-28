import { Handle, Position, NodeProps } from "reactflow";
import { motion } from "framer-motion";

export function ServiceNode({ data }: NodeProps) {
  const isDown = data.status === "down";
  const isDegraded = data.status === "degraded";

  const getStatusColor = () => {
    if (isDown) return "bg-red-500";
    if (isDegraded) return "bg-amber-500";
    return "bg-emerald-500";
  };

  const getBgClass = () => {
    if (isDown) return "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900/50";
    if (isDegraded) return "bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/50";
    return "bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-700";
  };

  return (
    <motion.div
      whileHover={{ scale: 1.05 }}
      whileTap={{ scale: 0.95 }}
      className={`relative rounded-2xl border p-4 shadow-sm w-48 ${getBgClass()}`}
    >
      <Handle type="target" position={Position.Left} className="w-2 h-2 rounded-full bg-slate-400" />

      <div className="flex items-center gap-2 mb-2">
        <div className="relative flex items-center justify-center">
          <div className={`w-3 h-3 rounded-full ${getStatusColor()}`} />
          {(isDown || isDegraded) && (
            <div
              className={`absolute inset-0 rounded-full animate-ping opacity-75 ${getStatusColor()}`}
            />
          )}
        </div>
        <div className="font-semibold text-sm text-slate-800 dark:text-slate-200 truncate">
          {data.label}
        </div>
      </div>

      <div className="space-y-1 text-xs text-slate-500 dark:text-slate-400">
        <div className="flex justify-between">
          <span>RPS:</span>
          <span className="font-medium text-slate-700 dark:text-slate-300">{data.req_rate}</span>
        </div>
        <div className="flex justify-between">
          <span>ERR:</span>
          <span className="font-medium text-slate-700 dark:text-slate-300">{data.error_rate}</span>
        </div>
      </div>

      <Handle type="source" position={Position.Right} className="w-2 h-2 rounded-full bg-slate-400" />
    </motion.div>
  );
}
