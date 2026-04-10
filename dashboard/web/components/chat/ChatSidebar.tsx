"use client";

import { useState, useRef, useEffect } from "react";

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
  const [open, setOpen] = useState(false);
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

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value);
        for (const line of chunk.split("\n")) {
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
              break;
            }
            if (token) {
              setMessages((m) => {
                const last = m[m.length - 1];
                return [...m.slice(0, -1), { ...last, content: last.content + token }];
              });
            }
          } catch { /* ignore */ }
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
    <>
      {/* Toggle tab — always visible on right edge */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="fixed right-0 top-1/2 -translate-y-1/2 z-40 bg-blue-600 hover:bg-blue-500 text-white px-1.5 py-4 rounded-l-lg shadow-lg text-xs font-medium"
        style={{ writingMode: "vertical-rl", textOrientation: "mixed" }}
        title="Claude Chat"
      >
        {open ? "▶ Close" : "◀ Claude"}
      </button>

      {/* Sidebar panel */}
      <div
        className={`fixed top-0 right-0 h-full z-30 flex flex-col bg-bg-page border-l border-border-primary shadow-xl transition-transform duration-300 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
        style={{ width: "400px" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border-primary">
          <span className="text-sm font-semibold text-text-primary">Claude Assistant</span>
          <button onClick={() => setOpen(false)} className="text-text-muted hover:text-text-primary text-lg leading-none">&times;</button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
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
                      ? "bg-blue-600 text-white"
                      : "bg-bg-card border border-border-primary text-text-primary"
                  }`}
                >
                  {text}
                  {msg.streaming && <span className="inline-block w-1.5 h-3 bg-current ml-0.5 animate-pulse" />}
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
        <div className="border-t border-border-primary p-3 flex gap-2">
          <input
            className="flex-1 bg-bg-card border border-border-primary rounded px-3 py-2 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:border-blue-500"
            placeholder="Ask Claude..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            disabled={streaming}
          />
          <button
            onClick={send}
            disabled={streaming || !input.trim()}
            className="px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs rounded disabled:opacity-50 shrink-0"
          >
            {streaming ? "…" : "Send"}
          </button>
        </div>
      </div>

      {/* Backdrop (mobile / small screens) */}
      {open && (
        <div
          className="fixed inset-0 z-20 bg-black/30 lg:hidden"
          onClick={() => setOpen(false)}
        />
      )}
    </>
  );
}
