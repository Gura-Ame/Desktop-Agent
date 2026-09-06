/** 把訊息的時間戳格式化成聊天氣泡上方那種簡短時間字串，沒有時間戳就回傳 null。
 * 原本 ChatMessage.tsx 裡有兩份幾乎一樣的邏輯（一般訊息 vs 任務樹訊息各寫一次），
 * 抽出來避免兩邊之後改格式又漏改一邊。
 */
export function formatTimeLabel(ts?: number): string | null {
	if (!ts) return null;
	return new Date(ts).toLocaleTimeString([], {
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
	});
}
