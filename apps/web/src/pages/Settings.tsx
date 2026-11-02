import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { getPlatform } from "@/lib/platform";
import { Toolbar, useSettings } from "@/components/shell/AppShell";
import { KeyValue, Panel, StatusLine } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type ProviderStatus = { name: string; installed: boolean; version: string; logged_in: boolean | null; detail: string };
type OriginStatus = { mode: "local" | "remote"; local_origin?: { installed: boolean; executable?: string }; vms: { name: string; status: string; ip: string | null }[]; bridge_url: string; token_configured: boolean; reachable: boolean; error?: string; health?: { version: string }; capabilities?: Record<string, unknown> };

const PROVIDER_LABEL: Record<string, string> = { codex: "Codex CLI（默认）", claude: "Claude Code CLI", anthropic_api: "Anthropic API", openai_api: "OpenAI 兼容 API" };

export default function Settings() {
  const localOrigin = getPlatform() === "windows";
  const credentialStore = localOrigin ? "Windows 凭据管理器" : "macOS 钥匙串";
  const qc = useQueryClient();
  const s = useSettings();
  const [token, setToken] = useState("");
  const [apiKey, setApiKey] = useState("");
  const providers = useQuery({ queryKey: ["ai-providers"], queryFn: () => api.get<{ providers: ProviderStatus[] }>("/ai/providers"), staleTime: 60_000 });
  const origin = useQuery({ queryKey: ["origin-status"], queryFn: () => api.get<OriginStatus>("/origin/status") });
  const update = useMutation({
    mutationFn: (patch: Record<string, unknown>) => api.put("/settings", patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
    onError: (e: Error) => toast.error(e.message),
  });
  const secret = useMutation({
    mutationFn: (b: { name: string; value: string }) => api.post("/settings/secrets", b),
    onSuccess: () => { toast.success(`已保存到${credentialStore}`); setToken(""); setApiKey(""); qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["origin-status"] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const pair = useMutation({
    mutationFn: () => api.post<{ bridge_url: string }>("/origin/pair", { vm_name: origin.data?.vms[0]?.name ?? "Windows 11" }),
    onSuccess: (r) => { toast.success(`已与 ${r.bridge_url} 配对`); qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["origin-status"] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const v = s.data;
  if (!v) return <><Toolbar title="设置" /><main className="p-4 text-fg-2">正在加载…</main></>;
  const set = (k: string, val: unknown) => update.mutate({ [k]: val });
  const secrets = (v.secrets ?? {}) as Record<string, boolean>;

  return (
    <>
      <Toolbar title="设置" />
      <main className="min-h-0 flex-1 overflow-auto p-3">
        <div className="mx-auto grid max-w-4xl gap-3">
          <Panel title="外观">
            <div className="flex flex-wrap items-center gap-6">
              <div className="flex items-center gap-2">
                <Label htmlFor="theme">外观</Label>
                <Select value={String(v.theme)} onValueChange={(x) => set("theme", x)}>
                  <SelectTrigger id="theme" className="h-7 w-32"><SelectValue /></SelectTrigger>
                  <SelectContent><SelectItem value="system">跟随系统</SelectItem><SelectItem value="light">浅色</SelectItem><SelectItem value="dark">深色</SelectItem></SelectContent>
                </Select>
              </div>
              <label className="flex items-center gap-2"><Switch checked={Boolean(v.reduce_transparency)} onCheckedChange={(c) => set("reduce_transparency", c)} />减少透明度（侧边栏改为不透明）</label>
              <div className="flex items-center gap-2">
                <Label htmlFor="op">操作者</Label>
                <Input id="op" className="h-7 w-40" defaultValue={String(v.operator ?? "")} onBlur={(e) => set("operator", e.target.value)} />
              </div>
            </div>
          </Panel>

          <Panel title="AI 助手">
            <div className="space-y-3">
              <label className="flex items-center gap-2"><Switch checked={Boolean(v.ai_enabled)} onCheckedChange={(c) => set("ai_enabled", c)} />启用 AI（关闭后规则识别与全部计算照常工作）</label>
              <StatusLine severity="info">CLI Provider 虽在本机运行，内容仍会发送到 OpenAI / Anthropic 的云端模型；默认只发送表头、单位与少量样例行，发送前会显示具体内容。</StatusLine>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="prov">Provider</Label>
                  <Select value={String(v.ai_provider)} onValueChange={(x) => set("ai_provider", x)}>
                    <SelectTrigger id="prov" className="h-7"><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="codex">Codex CLI（默认）</SelectItem><SelectItem value="claude">Claude Code CLI</SelectItem><SelectItem value="api">API 接入</SelectItem></SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="model">模型（留空用默认）</Label>
                  <Input id="model" className="h-7" defaultValue={String(v.ai_model ?? "")} onBlur={(e) => set("ai_model", e.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="effort">推理强度</Label>
                  <Select value={String(v.ai_effort || "default")} onValueChange={(x) => set("ai_effort", x === "default" ? "" : x)}>
                    <SelectTrigger id="effort" className="h-7"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">默认（由模型决定）</SelectItem>
                      <SelectItem value="low">低（更快、更省）</SelectItem>
                      <SelectItem value="medium">中</SelectItem>
                      <SelectItem value="high">高</SelectItem>
                      <SelectItem value="xhigh">很高</SelectItem>
                      <SelectItem value="max">最高（最慢、最耗 token）</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-subhead text-fg-2">作用于列映射、质量提示与文献对标；越高越慢、消耗越多。对 OpenAI 兼容接口只在推理模型上有效。</p>
                </div>
                {v.ai_provider === "api" && (
                  <>
                    <div className="space-y-1">
                      <Label htmlFor="kind">API 类型</Label>
                      <Select value={String(v.ai_api_kind)} onValueChange={(x) => set("ai_api_kind", x)}>
                        <SelectTrigger id="kind" className="h-7"><SelectValue /></SelectTrigger>
                        <SelectContent><SelectItem value="anthropic">Anthropic</SelectItem><SelectItem value="openai_compatible">OpenAI 兼容</SelectItem></SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="base">API 地址</Label>
                      <Input id="base" className="h-7" defaultValue={String(v.ai_api_base_url ?? "")} onBlur={(e) => set("ai_api_base_url", e.target.value)} />
                    </div>
                    <div className="space-y-1 sm:col-span-2">
                      <Label htmlFor="key">API Key（只保存到{credentialStore}，{secrets[v.ai_api_kind === "openai_compatible" ? "openai_api_key" : "anthropic_api_key"] ? "已配置" : "未配置"}）</Label>
                      <div className="flex gap-2">
                        <Input id="key" type="password" autoComplete="off" className="h-7" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
                        <Button size="sm" variant="outline" disabled={!apiKey} onClick={() => secret.mutate({ name: v.ai_api_kind === "openai_compatible" ? "openai_api_key" : "anthropic_api_key", value: apiKey })}>保存</Button>
                      </div>
                    </div>
                  </>
                )}
              </div>
              <table className="w-full text-body">
                <thead><tr className="border-b text-left text-fg-2"><th className="py-1 font-medium">Provider</th><th className="font-medium">安装</th><th className="font-medium">版本</th><th className="font-medium">登录/配置</th></tr></thead>
                <tbody>
                  {providers.isPending && <tr><td colSpan={4} className="py-1 text-fg-2">正在检测 Provider…</td></tr>}
                  {providers.data?.providers.map((p) => (
                    <tr key={p.name} className="border-b">
                      <td className="py-1">{PROVIDER_LABEL[p.name] ?? p.name}</td>
                      <td>{p.installed ? "是" : "否"}</td>
                      <td className="text-fg-2">{p.version || "—"}</td>
                      <td>{p.logged_in === null ? "未知" : p.logged_in ? "是" : "否"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title={localOrigin ? "本机 Origin" : "Origin Bridge"} actions={<Button size="sm" variant="outline" onClick={() => origin.refetch()} disabled={origin.isFetching}>{origin.isFetching ? "正在测试…" : "测试连接"}</Button>}>
            <div className="space-y-3">
              {origin.data?.reachable ? <StatusLine severity="success">已连接（Bridge {origin.data.health?.version}）</StatusLine> : <StatusLine severity="warning">{origin.data?.error ?? "未连接"}</StatusLine>}
              {!localOrigin && <>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="burl">Bridge 地址</Label>
                  <Input id="burl" className="h-7" placeholder="http://<虚拟机 IP>:8766" defaultValue={String(v.bridge_url ?? "")} onBlur={(e) => set("bridge_url", e.target.value.trim())} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="btok">认证 Token（{secrets.bridge_token ? "已配置" : "未配置"}，只保存到{credentialStore}）</Label>
                  <div className="flex gap-2">
                    <Input id="btok" type="password" autoComplete="off" className="h-7" value={token} onChange={(e) => setToken(e.target.value)} />
                    <Button size="sm" variant="outline" disabled={!token} onClick={() => secret.mutate({ name: "bridge_token", value: token })}>保存</Button>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" onClick={() => pair.mutate()} disabled={pair.isPending}>{pair.isPending ? "正在配对…" : "从虚拟机自动配对"}</Button>
                <span className="text-subhead text-fg-2">通过 prlctl 读取 Bridge 地址与 Token；也可以手动填写。</span>
              </div>
              </>}
              {localOrigin && <StatusLine severity="info">直接使用已安装的 x64 Origin。无需虚拟机、地址或认证 Token；导出时启动独立实例，退出时自动关闭。</StatusLine>}
              <KeyValue items={[
                [localOrigin ? "本机 Origin" : "Parallels 虚拟机", localOrigin ? (origin.data?.local_origin?.executable ?? "未检测到已注册的 Origin") : origin.data?.vms.map((m) => `${m.name}（${m.status}${m.ip ? `，${m.ip}` : ""}）`).join("；") || "未检测到（prlctl 不可用）"],
                ["Origin 自动化", origin.data?.capabilities ? (origin.data.capabilities.originpro_importable ? "originpro 可用" : "originpro 不可用") : "—"],
                ["Bridge Python", origin.data?.capabilities ? `${origin.data.capabilities.python}（${origin.data.capabilities.python_bits} 位）` : "—"],
              ]} />
            </div>
          </Panel>

          <Panel title="单位与存储">
            <div className="flex flex-wrap items-center gap-6">
              <div className="flex items-center gap-2">
                <Label htmlFor="su">应力显示单位</Label>
                <Select value={String(v.stress_display_unit)} onValueChange={(x) => set("stress_display_unit", x)}>
                  <SelectTrigger id="su" className="h-7 w-24"><SelectValue /></SelectTrigger>
                  <SelectContent>{["kPa", "MPa", "GPa"].map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <span className="text-fg-2">数据目录由启动参数 POLYMECH_DATA_DIR 决定；原始文件只读归档并校验 SHA-256。</span>
            </div>
          </Panel>
        </div>
      </main>
    </>
  );
}
