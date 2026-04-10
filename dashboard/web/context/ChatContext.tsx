"use client";
import { createContext, useContext, useState, ReactNode } from "react";

interface ChatContextValue {
  open: boolean;
  toggle: () => void;
}

const ChatContext = createContext<ChatContextValue>({ open: false, toggle: () => {} });

export function ChatProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <ChatContext.Provider value={{ open, toggle: () => setOpen((o) => !o) }}>
      {children}
    </ChatContext.Provider>
  );
}

export const useChat = () => useContext(ChatContext);
