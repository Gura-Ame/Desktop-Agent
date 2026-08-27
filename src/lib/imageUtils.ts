import type { ChatImage } from '../types';

/**
 * 壓縮圖片再送給本地 Vision 模型（GGUF / llama.cpp 對超大 data URL 很不穩）
 * @returns data URL (jpeg)
 */
export function compressImageDataUrl(
  dataUrl: string,
  maxSide = 1280,
  quality = 0.85,
): Promise<string> {
  return new Promise((resolve) => {
    if (!dataUrl || typeof dataUrl !== 'string') {
      resolve(dataUrl);
      return;
    }
    const img = new Image();
    img.onload = () => {
      let { width, height } = img;
      if (width <= maxSide && height <= maxSide && dataUrl.length < 800_000) {
        resolve(dataUrl);
        return;
      }
      const scale = Math.min(1, maxSide / Math.max(width, height));
      width = Math.round(width * scale);
      height = Math.round(height * scale);
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        resolve(dataUrl);
        return;
      }
      ctx.drawImage(img, 0, 0, width, height);
      try {
        resolve(canvas.toDataURL('image/jpeg', quality));
      } catch {
        resolve(dataUrl);
      }
    };
    img.onerror = () => resolve(dataUrl);
    img.src = dataUrl;
  });
}

export async function compressImages(images: ChatImage[]): Promise<ChatImage[]> {
  const out: ChatImage[] = [];
  for (const img of images) {
    const dataUrl = await compressImageDataUrl(img.dataUrl);
    out.push({ ...img, dataUrl });
  }
  return out;
}
