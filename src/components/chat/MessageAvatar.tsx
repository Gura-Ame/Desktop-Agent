import { Bot, User } from "lucide-react";

type MessageAvatarProps = {
	role: "user" | "agent";
};

/** 聊天泡泡兩側的圓角方形頭像圖示。使用者跟 agent 各一種配色。 */
export default function MessageAvatar({ role }: MessageAvatarProps) {
	if (role === "user") {
		return (
			<div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-zinc-300 bg-zinc-100 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
				<User size={14} />
			</div>
		);
	}
	return (
		<div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-zinc-200 bg-white text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
			<Bot size={14} />
		</div>
	);
}
