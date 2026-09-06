import { FileText } from "lucide-react";
import type { ChatFile } from "../../types";

type MessageFileAttachmentsProps = {
	files: ChatFile[] | undefined;
};

/** 使用者訊息裡附加的檔案路徑列——跟 MessageImageAttachments 同樣定位，
 * 但這裡顯示的是路徑本身（滑鼠移過去看完整路徑），不是檔案內容的預覽，
 * 因為這個 App 從來沒有真的把檔案內容搬進瀏覽器端，見
 * useMessageComposer.ts 的 pickFiles() 說明。
 */
export default function MessageFileAttachments({
	files,
}: MessageFileAttachmentsProps) {
	if (!files?.length) return null;
	return (
		<div className="mb-2 flex flex-wrap gap-1.5">
			{files.map((file) => (
				<span
					key={file.id}
					title={file.path}
					className="flex items-center gap-1 rounded-md border border-black/10 bg-black/5 px-2 py-1 text-xs dark:border-white/10 dark:bg-white/10"
				>
					<FileText size={12} className="shrink-0 opacity-70" />
					<span className="max-w-[180px] truncate">{file.name}</span>
				</span>
			))}
		</div>
	);
}
