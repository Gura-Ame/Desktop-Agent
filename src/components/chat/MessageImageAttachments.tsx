import type { ChatImage } from "../../types";

type MessageImageAttachmentsProps = {
	images: ChatImage[] | undefined;
};

/** 使用者訊息裡附帶的圖片縮圖列，點了可以開新分頁看原圖。 */
export default function MessageImageAttachments({
	images,
}: MessageImageAttachmentsProps) {
	if (!images?.length) return null;
	return (
		<div className="mb-2 flex flex-wrap gap-2">
			{images.map((img) => (
				<a
					key={img.id || img.name}
					href={img.dataUrl}
					target="_blank"
					rel="noreferrer"
					className="block overflow-hidden rounded-md border border-zinc-200 dark:border-zinc-700"
				>
					<img
						src={img.dataUrl}
						alt={img.name || "attachment"}
						className="max-h-40 max-w-[200px] object-contain"
					/>
				</a>
			))}
		</div>
	);
}
