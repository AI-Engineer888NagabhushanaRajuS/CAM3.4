import { useSyncExternalStore } from 'react';

/**
 * Which model family the RFQ assistant asks: Local (Ollama), OpenRouter (cloud) or Auto. One store, so the model menu and the
 * chat's own switch always agree. Remembered per browser; storage blocked means Auto.
 */
export type ChatProviderMode = 'auto' | 'local' | 'openrouter';

const KEY = 'cam-chat-provider';
const EVENT = 'cam:chat-provider';

export function readChatProvider(): ChatProviderMode {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'local' || v === 'openrouter' ? v : 'auto';
  } catch {
    return 'auto';
  }
}

export function setChatProvider(mode: ChatProviderMode): void {
  try {
    localStorage.setItem(KEY, mode);
  } catch {
    // Not remembered; the change still applies to the open chat below.
  }
  window.dispatchEvent(new Event(EVENT));
}

const subscribe = (onChange: () => void) => {
  window.addEventListener(EVENT, onChange);
  return () => window.removeEventListener(EVENT, onChange);
};

export function useChatProvider(): ChatProviderMode {
  return useSyncExternalStore(subscribe, readChatProvider, () => 'auto' as ChatProviderMode);
}
