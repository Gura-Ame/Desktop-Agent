import { useCallback, useEffect, useRef } from 'react';

const NEAR_BOTTOM_PX = 80;

export function useChatScroll(messages, isStreamingRef) {
  const chatEndRef = useRef(null);
  const scrollContainerRef = useRef(null);
  const stickToBottomRef = useRef(true);

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distance <= NEAR_BOTTOM_PX;
  }, []);

  const scrollToBottom = useCallback((behavior = 'smooth') => {
    const el = scrollContainerRef.current;
    if (!el) {
      chatEndRef.current?.scrollIntoView({ behavior });
      return;
    }
    if (behavior === 'auto') {
      el.scrollTop = el.scrollHeight;
    } else {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
  }, []);

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    const behavior = isStreamingRef.current ? 'auto' : 'smooth';
    const id = requestAnimationFrame(() => scrollToBottom(behavior));
    return () => cancelAnimationFrame(id);
  }, [messages, isStreamingRef, scrollToBottom]);

  const pinToBottom = useCallback(() => {
    stickToBottomRef.current = true;
  }, []);

  return {
    chatEndRef,
    scrollContainerRef,
    stickToBottomRef,
    handleScroll,
    scrollToBottom,
    pinToBottom,
  };
}
