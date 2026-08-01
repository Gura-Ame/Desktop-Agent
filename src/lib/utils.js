/** 合併 className，略過 falsy */
export function cn(...parts) {
  return parts.filter(Boolean).join(' ');
}
