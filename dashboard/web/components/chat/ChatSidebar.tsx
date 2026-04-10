"use client";

import { useState, useRef, useEffect } from "react";
import { useChat } from "@/context/ChatContext";

interface Message {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

interface ActionBlock {
  type: string;
  bot_id: string;
  field: string;
  value: unknown;
}

function parseAction(content: string): ActionBlock | null {
  const match = content.match(/```action\n([\s\S]*?)\n```/);
  if (!match) return null;
  try { return JSON.parse(match[1]); } catch { return null; }
}

function displayContent(content: string): string {
  return content.replace(/```action[\s\S]*?```/g, "").trim();
}

export default function ChatSidebar() {
  const { open, toggle } = useChat();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    if (!input.trim() || streaming) return;
    const text = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setStreaming(true);
    setMessages((m) => [...m, { role: "assistant", content: "", streaming: true }]);

    try {
      const res = await fetch("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
        credentials: "include",
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (raw === "[DONE]") break;
          try {
            const { token, error } = JSON.parse(raw);
            if (error) {
              setMessages((m) => {
                const last = m[m.length - 1];
                return [...m.slice(0, -1), { ...last, content: `Error: ${error}`, streaming: false }];
              });
              return;
            }
            if (token) {
              setMessages((m) => {
                const last = m[m.length - 1];
                return [...m.slice(0, -1), { ...last, content: last.content + token }];
              });
            }
          } catch { /* ignore malformed */ }
        }
      }
    } catch (e) {
      setMessages((m) => {
        const last = m[m.length - 1];
        return [...m.slice(0, -1), { ...last, content: `Connection error: ${e}`, streaming: false }];
      });
    } finally {
      setMessages((m) => {
        const last = m[m.length - 1];
        if (!last || last.role !== "assistant") return m;
        return [...m.slice(0, -1), { ...last, streaming: false }];
      });
      setStreaming(false);
    }
  };

  const applyAction = async (action: ActionBlock) => {
    try {
      const res = await fetch(`/api/bots/${action.bot_id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ [action.field]: action.value }),
      });
      if (!res.ok) throw new Error(await res.text());
      setMessages((m) => [
        ...m,
        { role: "assistant", content: `Applied: Bot ${action.bot_id} ${action.field} → ${action.value}` },
      ]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `Failed to apply: ${e}` }]);
    }
  };

  return (
    <div className="flex flex-shrink-0 h-full">
      {/* Toggle tab — always visible vertical strip */}
      <button
        onClick={toggle}
        className="w-8 flex items-center justify-center bg-bg-card border-l border-border-primary hover:bg-bg-card-hover transition-colors"
        title={open ? "Close chat" : "Open Claude chat"}
      >
        <span
          className="text-[11px] font-medium text-text-secondary select-none"
          style={{ writingMode: "vertical-rl", textOrientation: "mixed" }}
        >
          {open ? "▶ Close" : "◀ Claude"}
        </span>
      </button>

      {/* Sliding content panel */}
      <div
        className="overflow-hidden transition-[width] duration-300 flex flex-col bg-bg-card border-l border-border-primary"
        style={{ width: open ? "400px" : "0px" }}
      >
        <div className="w-[400px] flex flex-col h-full">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-border-primary shrink-0">
            <span className="text-sm font-semibold text-text-primary">Claude Assistant</span>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
            {messages.length === 0 && (
              <p className="text-xs text-text-muted text-center mt-8">
                Ask Claude about your bots, trades, or strategy.<br />
                <span className="opacity-60">Config changes can be applied with one click.</span>
              </p>
            )}
            {messages.map((msg, i) => {
              const action = msg.role === "assistant" ? parseAction(msg.content) : null;
              const text = displayContent(msg.content);
              return (
                <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[90%] rounded-xl px-3 py-2 text-xs whitespace-pre-wrap break-words ${
                      msg.role === "user"
                        ? "bg-accent-blue text-white"
                        : "bg-bg-page border border-border-primary text-text-primary"
                    }`}
                  >
                    {text}
                    {msg.streaming && (
                      <span className="inline-block w-1.5 h-3 bg-current ml-0.5 animate-pulse" />
                    )}
                    {action && !msg.streaming && (
                      <button
                        onClick={() => applyAction(action)}
                        className="mt-2 block w-full text-xs bg-green-700 hover:bg-green-600 text-white rounded px-2 py-1"
                      >
                        Apply: {action.field} = {String(action.value)} (Bot {action.bot_id})
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="border-t border-border-primary p-3 flex gap-2 shrink-0">
            <input
              className="flex-1 bg-bg-page border border-border-primary rounded px-3 py-2 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:border-accent-blue"
              placeholder="Ask Claude..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
              }}
              disabled={streaming}
            />
            <button
              onClick={send}
              disabled={streaming || !input.trim()}
              className="px-3 py-2 bg-accent-blue hover:bg-blue-500 text-white text-xs rounded disabled:opacity-50 shrink-0"
            >
              {streaming ? "…" : "Send"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
