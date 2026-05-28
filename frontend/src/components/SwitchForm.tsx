import { useState } from "react";
import type { NetworkSwitch } from "../client";

interface Props {
  initial?: NetworkSwitch;
  onSave: (data: Record<string, unknown>) => void;
  onCancel: () => void;
}

export default function SwitchForm({ initial, onSave, onCancel }: Props) {
  const [name, setName] = useState(initial?.name ?? "");
  const [ip, setIp] = useState(initial?.ip_address ?? "");
  const [username, setUsername] = useState(initial?.ssh_username ?? "admin");
  const [password, setPassword] = useState("");
  const [enablePwd, setEnablePwd] = useState("");
  const [port, setPort] = useState(initial?.ssh_port ?? 22);
  const [vlan, setVlan] = useState(initial?.ap_vlan ?? 20);
  const [vendor, setVendor] = useState<"cisco" | "dlink" | "generic">(
    (initial?.vendor as "cisco" | "dlink" | "generic") ?? "cisco",
  );
  const [protocol, setProtocol] = useState<"snmp" | "ssh" | "snmp+ssh">(
    (initial?.management_protocol as "snmp" | "ssh" | "snmp+ssh") ?? "snmp+ssh",
  );
  const [snmpVersion, setSnmpVersion] = useState<"2c">(
    (initial?.snmp_version as "2c") ?? "2c",
  );
  const [snmpRo, setSnmpRo] = useState(initial?.snmp_community_ro ?? "public");
  const [snmpRw, setSnmpRw] = useState(initial?.snmp_community_rw ?? "");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const data: Record<string, unknown> = {
      name: name.trim(),
      ip_address: ip.trim(),
      ssh_username: username.trim(),
      ssh_port: port,
      ap_vlan: vlan,
      vendor,
      management_protocol: protocol,
      snmp_version: snmpVersion,
      snmp_community_ro: snmpRo.trim(),
    };
    if (snmpRw.trim()) data.snmp_community_rw = snmpRw.trim();
    if (password) data.ssh_password = password;
    if (enablePwd) data.enable_password = enablePwd;
    if (!initial) {
      data.ssh_password = password;
      data.enable_password = enablePwd;
    }
    onSave(data);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-xl p-6 w-full max-w-md space-y-4">
        <h3 className="text-lg font-semibold text-gray-900">
          {initial ? "Редактировать свитч" : "Добавить свитч"}
        </h3>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Название</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            placeholder="Магазин А1 - свитч"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">IP-адрес</label>
            <input
              value={ip}
              onChange={(e) => setIp(e.target.value)}
              required
              placeholder="10.10.98.1"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">SSH порт</label>
            <input
              type="number"
              value={port}
              onChange={(e) => setPort(Number(e.target.value))}
              min={1}
              max={65535}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Вендор</label>
            <select
              value={vendor}
              onChange={(e) => setVendor(e.target.value as "cisco" | "dlink" | "generic")}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            >
              <option value="cisco">Cisco</option>
              <option value="dlink">D-Link</option>
              <option value="generic">Generic SNMP</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Протокол</label>
            <select
              value={protocol}
              onChange={(e) => setProtocol(e.target.value as "snmp" | "ssh" | "snmp+ssh")}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            >
              <option value="snmp+ssh">SNMP + SSH</option>
              <option value="snmp">SNMP</option>
              <option value="ssh">SSH</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">SSH логин</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">VLAN точек доступа</label>
            <input
              type="number"
              value={vlan}
              onChange={(e) => setVlan(Number(e.target.value))}
              min={1}
              max={4094}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">SNMP ver</label>
            <select
              value={snmpVersion}
              onChange={(e) => setSnmpVersion(e.target.value as "2c")}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            >
              <option value="2c">2c</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">SNMP RO</label>
            <input
              value={snmpRo}
              onChange={(e) => setSnmpRo(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">SNMP RW</label>
            <input
              value={snmpRw}
              onChange={(e) => setSnmpRw(e.target.value)}
              placeholder="optional"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            SSH пароль {initial && <span className="text-gray-400">(оставьте пустым, чтобы не менять)</span>}
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required={!initial}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Enable пароль {initial && <span className="text-gray-400">(оставьте пустым, чтобы не менять)</span>}
          </label>
          <input
            type="password"
            value={enablePwd}
            onChange={(e) => setEnablePwd(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
          />
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 rounded-lg hover:bg-gray-100 transition"
          >
            Отмена
          </button>
          <button
            type="submit"
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition"
          >
            {initial ? "Сохранить" : "Добавить"}
          </button>
        </div>
      </form>
    </div>
  );
}
