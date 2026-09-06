import { Check, ShieldAlert, ShieldQuestion, X } from "lucide-react";
import { cn } from "../../lib/utils";
import type { PermissionDecision, PermissionInfo, ToolRisk } from "../../types";
import { Button } from "../ui/Button";
import MessageAvatar from "./MessageAvatar";

type PermissionRequestMessageProps = {
	info: PermissionInfo;
	resolved?: PermissionDecision;
	onRespond: (decision: PermissionDecision) => void;
};

const RISK_STYLE: Record<
	ToolRisk,
	{ label: string; badgeClass: string }
> = {
	safe: {
		label: "低風險",
		badgeClass:
			"bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
	},
	moderate: {
		label: "中風險",
		badgeClass:
			"bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300",
	},
	dangerous: {
		label: "高風險",
		badgeClass:
			"bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300",
	},
};

const RESOLVED_LABEL: Record<PermissionDecision, string> = {
	allow: "已允許這一次",
	allow_session: "已允許本次工作階段",
	deny: "已拒絕",
};

/** agent 想呼叫一個風險較高的工具時彈出的授權卡片——跟 TaskTreeMessage 一樣是
 * 一種特殊訊息型態，從 ChatMessage.tsx 依 msg.isPermissionRequest 路由過來。
 * 三個按鈕分別對應後端 request_tool_permission 認得的三種 decision 字串。
 */
export default function PermissionRequestMessage({
	info,
	resolved,
	onRespond,
}: PermissionRequestMessageProps) {
	const risk = RISK_STYLE[info.risk] ?? RISK_STYLE.dangerous;

	return (
		<div className="mx-auto flex max-w-3xl min-w-0 gap-3 justify-start">
			<MessageAvatar role="agent" />
			<div className="min-w-0 max-w-[min(85%,42rem)] flex-1">
				<div className="rounded-lg rounded-bl-sm border border-amber-300/60 bg-amber-50 px-3.5 py-3 text-sm dark:border-amber-900/50 dark:bg-amber-950/20">
					<div className="mb-2 flex items-center gap-2">
						<ShieldQuestion
							size={15}
							className="shrink-0 text-amber-600 dark:text-amber-400"
						/>
						<span className="font-medium text-amber-900 dark:text-amber-200">
							Agent 想要執行一個需要授權的動作
						</span>
						<span
							className={cn(
								"ml-auto rounded-full px-2 py-0.5 text-[10px] font-medium",
								risk.badgeClass,
							)}
						>
							{risk.label}
						</span>
					</div>

					<div className="mb-3 space-y-0.5 rounded-md bg-white/60 px-2.5 py-2 font-mono text-xs text-zinc-700 dark:bg-black/20 dark:text-zinc-300">
						<div>
							工具：<span className="font-semibold">{info.tool}</span>
						</div>
						{info.args && <div className="truncate">參數：{info.args}</div>}
					</div>

					{resolved ? (
						<div className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
							{resolved === "deny" ? (
								<X size={13} className="text-rose-500" />
							) : (
								<Check size={13} className="text-emerald-600 dark:text-emerald-400" />
							)}
							{RESOLVED_LABEL[resolved]}
						</div>
					) : (
						<div className="flex flex-wrap gap-1.5">
							<Button
								size="sm"
								variant="primary"
								onClick={() => onRespond("allow")}
							>
								<Check size={13} /> 允許這一次
							</Button>
							<Button
								size="sm"
								variant="secondary"
								onClick={() => onRespond("allow_session")}
							>
								<ShieldAlert size={13} /> 本次工作階段永久允許
							</Button>
							<Button
								size="sm"
								variant="destructive"
								onClick={() => onRespond("deny")}
							>
								<X size={13} /> 拒絕
							</Button>
						</div>
					)}
				</div>
			</div>
		</div>
	);
}
