import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Camera, RotateCcw, Zap } from "lucide-react";
import type { CameraPort } from "../client";
import { setSwitchPortPoe } from "../client";
import { useConfirm } from "./ConfirmDialog";
import { showToast } from "../lib/toastBus";

interface Props {
  cam: CameraPort;
  switchId: string;
  isSuperuser: boolean;
}

export default function CameraPortRow({ cam, switchId, isSuperuser }: Props) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const [rebooting, setRebooting] = useState(false);
  const isDown = cam.oper_status !== "connected";

  const rebootMut = useMutation({
    mutationFn: () => setSwitchPortPoe(switchId, cam.port, "cycle"),
    onSuccess: () => showToast(`Камера на порту ${cam.port} перезагружена`, "success"),
    onSettled: () => {
      setRebooting(false);
      queryClient.invalidateQueries({ queryKey: ["switch-camera-ports", switchId] });
    },
  });

  const handleReboot = async () => {
    if (await confirm(`Перезагрузить камеру на порту ${cam.port} (VLAN ${cam.vlan})?`, { danger: true, confirmText: "Перезагрузить" })) {
      setRebooting(true);
      rebootMut.mutate();
    }
  };

  return (
    <div className={`flex items-center gap-3 py-2 px-3 rounded-lg group text-xs ${isDown ? "bg-red-50" : "hover:bg-gray-50"}`}>
      <Camera className={`h-3.5 w-3.5 shrink-0 ${isDown ? "text-red-500" : "text-sky-500"}`} />
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className={`font-medium ${isDown ? "text-red-700" : "text-gray-800"}`}>{cam.description || cam.port}</span>
          <span className="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">VLAN {cam.vlan}</span>
          {isDown && (
            <span className="text-[10px] text-red-700 bg-red-100 px-1.5 py-0.5 rounded font-medium">
              нет линка
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-gray-500 mt-0.5">
          <span className="font-mono">{cam.port}</span>
          {cam.poe_power && cam.poe_power !== "0.0W" && (
            <span className="inline-flex items-center gap-0.5 text-amber-600">
              <Zap className="h-3 w-3" />{cam.poe_power}
            </span>
          )}
        </div>
      </div>
      {isSuperuser && (
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition">
          <button
            onClick={handleReboot}
            disabled={rebooting}
            className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-600 transition disabled:opacity-40"
            title="Перезагрузить камеру (PoE cycle)"
          >
            <RotateCcw className={`h-3.5 w-3.5 ${rebooting ? "animate-spin" : ""}`} />
          </button>
        </div>
      )}
    </div>
  );
}
