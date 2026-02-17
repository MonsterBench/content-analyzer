"use client";

import { useEffect, useState, useRef, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import {
  getCreators,
  createChatSession,
  getChatSessions,
  getChatMessages,
  sendMessage,
  sendMessageWithFiles,
  deleteChatSession,
  type Creator,
  type ChatSession,
  type ChatMessage,
} from "@/lib/api";

function ThinkingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="rounded-lg px-4 py-3 bg-[var(--muted)] flex items-center gap-1.5">
        <span
          className="w-2 h-2 rounded-full bg-[var(--muted-foreground)] animate-bounce"
          style={{ animationDelay: "0ms" }}
        />
        <span
          className="w-2 h-2 rounded-full bg-[var(--muted-foreground)] animate-bounce"
          style={{ animationDelay: "150ms" }}
        />
        <span
          className="w-2 h-2 rounded-full bg-[var(--muted-foreground)] animate-bounce"
          style={{ animationDelay: "300ms" }}
        />
      </div>
    </div>
  );
}

function AutoResizeTextarea({
  value,
  onChange,
  onKeyDown,
  placeholder,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  placeholder: string;
  disabled: boolean;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, []);

  useEffect(() => {
    resize();
  }, [value, resize]);

  return (
    <textarea
      ref={textareaRef}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={onKeyDown}
      placeholder={placeholder}
      disabled={disabled}
      rows={1}
      className="flex-1 px-3 py-2 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] disabled:opacity-50 resize-none overflow-y-auto leading-relaxed"
      style={{ maxHeight: "200px" }}
    />
  );
}

function ChatInner() {
  const searchParams = useSearchParams();
  const initialCreatorId = searchParams.get("creator");

  const [creators, setCreators] = useState<Creator[]>([]);
  const [selectedCreatorId, setSelectedCreatorId] = useState<number | null>(
    initialCreatorId ? parseInt(initialCreatorId) : null
  );
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [waiting, setWaiting] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const streamingTextRef = useRef("");
  const [streamingDisplay, setStreamingDisplay] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    getCreators().then(setCreators);
  }, []);

  useEffect(() => {
    if (selectedCreatorId) {
      getChatSessions(selectedCreatorId).then(setSessions);
    }
  }, [selectedCreatorId]);

  useEffect(() => {
    if (activeSessionId) {
      getChatMessages(activeSessionId).then(setMessages);
      setSidebarOpen(false); // Close sidebar on mobile when selecting a chat
    }
  }, [activeSessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingDisplay, waiting]);

  const handleNewChat = async () => {
    if (!selectedCreatorId) return;
    const session = await createChatSession(selectedCreatorId);
    setSessions((prev) => [session, ...prev]);
    setActiveSessionId(session.id);
    setMessages([]);
    setSidebarOpen(false);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    // Cap at 3 files total
    setAttachedFiles((prev) => [...prev, ...selected].slice(0, 3));
    // Reset input so re-selecting the same file works
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const removeFile = (index: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSend = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!input.trim() || !activeSessionId || waiting || streaming) return;

    const userMsg = input.trim();
    const filesToSend = [...attachedFiles];
    setInput("");
    setAttachedFiles([]);

    const displayContent = filesToSend.length > 0
      ? `${userMsg}\n\n[Attached: ${filesToSend.map((f) => f.name).join(", ")}]`
      : userMsg;

    setMessages((prev) => [
      ...prev,
      {
        id: Date.now(),
        session_id: activeSessionId,
        role: "user",
        content: displayContent,
        created_at: new Date().toISOString(),
      },
    ]);

    setWaiting(true);
    streamingTextRef.current = "";
    setStreamingDisplay("");

    try {
      let gotFirstChunk = false;

      const onChunk = (chunk: string) => {
        if (!gotFirstChunk) {
          gotFirstChunk = true;
          setWaiting(false);
          setStreaming(true);
        }
        streamingTextRef.current += chunk;
        setStreamingDisplay(streamingTextRef.current);
      };

      if (filesToSend.length > 0) {
        await sendMessageWithFiles(activeSessionId, userMsg, filesToSend, onChunk);
      } else {
        await sendMessage(activeSessionId, userMsg, onChunk);
      }

      const finalText = streamingTextRef.current;
      setStreaming(false);
      setStreamingDisplay("");
      streamingTextRef.current = "";

      if (finalText) {
        setMessages((prev) => [
          ...prev,
          {
            id: Date.now() + 1,
            session_id: activeSessionId,
            role: "assistant",
            content: finalText,
            created_at: new Date().toISOString(),
          },
        ]);
      }
    } catch (err) {
      console.error(err);
      setStreaming(false);
      setStreamingDisplay("");
      streamingTextRef.current = "";

      const errorMessage = err instanceof Error ? err.message : "Unknown error";
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          session_id: activeSessionId,
          role: "assistant",
          content: `Something went wrong: ${errorMessage}\n\nPlease try sending your message again.`,
          created_at: new Date().toISOString(),
        },
      ]);
    }

    setWaiting(false);

    if (selectedCreatorId) {
      getChatSessions(selectedCreatorId).then(setSessions);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleDeleteSession = async (sessionId: number) => {
    await deleteChatSession(sessionId);
    setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    if (activeSessionId === sessionId) {
      setActiveSessionId(null);
      setMessages([]);
    }
  };

  const isBusy = waiting || streaming;

  const suggestedQuestions = [
    "What are the main themes in this creator's content?",
    "Which posts got the most engagement and why?",
    "How does their Instagram content differ from YouTube?",
    "What posting patterns or trends do you notice?",
    "What recommendations would you give to improve engagement?",
  ];

  return (
    <div className="flex h-[calc(100vh-5rem)] sm:h-[calc(100vh-8rem)] gap-0 sm:gap-4 -mx-4 sm:mx-0">
      {/* Mobile header bar */}
      <div className="fixed top-14 left-0 right-0 z-20 flex items-center gap-2 px-3 py-2 bg-[var(--card)] border-b border-[var(--border)] sm:hidden">
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="p-1.5 rounded-md hover:bg-[var(--muted)]"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <span className="text-sm font-medium truncate">
          {activeSessionId
            ? sessions.find((s) => s.id === activeSessionId)?.title || "Chat"
            : "Select a chat"}
        </span>
      </div>

      {/* Sidebar overlay for mobile */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 sm:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div
        className={`fixed sm:static z-40 top-0 left-0 h-full w-72 sm:w-64 flex-shrink-0 flex flex-col bg-[var(--card)] border-r sm:border border-[var(--border)] sm:rounded-lg overflow-hidden transition-transform sm:transition-none ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full sm:translate-x-0"
        }`}
      >
        <div className="p-3 border-b border-[var(--border)]">
          <div className="flex items-center justify-between sm:hidden mb-2">
            <span className="text-sm font-semibold">Chats</span>
            <button onClick={() => setSidebarOpen(false)} className="p-1 rounded-md hover:bg-[var(--muted)]">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <select
            value={selectedCreatorId || ""}
            onChange={(e) => {
              setSelectedCreatorId(
                e.target.value ? parseInt(e.target.value) : null
              );
              setActiveSessionId(null);
              setMessages([]);
            }}
            className="w-full px-2 py-1.5 bg-[var(--background)] border border-[var(--border)] rounded-md text-sm"
          >
            <option value="">Select creator...</option>
            {creators.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>

        {selectedCreatorId && (
          <>
            <button
              onClick={handleNewChat}
              className="mx-3 mt-3 px-3 py-1.5 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-md text-sm font-medium hover:opacity-90"
            >
              New Chat
            </button>
            <div className="flex-1 overflow-y-auto p-3 space-y-1">
              {sessions.map((s) => (
                <div
                  key={s.id}
                  className={`flex items-center justify-between rounded-md px-2 py-1.5 text-sm cursor-pointer group ${
                    s.id === activeSessionId
                      ? "bg-[var(--accent)]"
                      : "hover:bg-[var(--muted)]"
                  }`}
                >
                  <span
                    className="truncate flex-1"
                    onClick={() => setActiveSessionId(s.id)}
                  >
                    {s.title}
                  </span>
                  <button
                    onClick={() => handleDeleteSession(s.id)}
                    className="text-[var(--muted-foreground)] hover:text-[var(--destructive)] opacity-0 group-hover:opacity-100 ml-1 text-xs"
                  >
                    x
                  </button>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Chat Area */}
      <div className="flex-1 flex flex-col bg-[var(--card)] sm:border border-[var(--border)] sm:rounded-lg overflow-hidden mt-10 sm:mt-0">
        {!activeSessionId ? (
          <div className="flex-1 flex items-center justify-center p-4">
            <div className="text-center max-w-md">
              <h2 className="text-lg font-semibold mb-2">
                {selectedCreatorId
                  ? "Start a new chat"
                  : "Select a creator to chat about"}
              </h2>
              <p className="text-sm text-[var(--muted-foreground)] mb-4">
                Ask questions about their content across all platforms. The AI
                uses RAG to find relevant content and provide data-backed
                insights.
              </p>
              {selectedCreatorId && (
                <button
                  onClick={handleNewChat}
                  className="px-4 py-2 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-md text-sm font-medium"
                >
                  New Chat
                </button>
              )}
            </div>
          </div>
        ) : (
          <>
            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-3 sm:p-4 space-y-4">
              {messages.length === 0 && !isBusy && (
                <div className="space-y-2 mt-8">
                  <p className="text-sm text-[var(--muted-foreground)] text-center mb-4">
                    Try asking a question:
                  </p>
                  {suggestedQuestions.map((q) => (
                    <button
                      key={q}
                      onClick={() => setInput(q)}
                      className="block w-full text-left text-sm px-4 py-2 rounded-md border border-[var(--border)] hover:bg-[var(--muted)] transition-colors"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              )}

              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex ${
                    msg.role === "user" ? "justify-end" : "justify-start"
                  }`}
                >
                  {msg.role === "user" ? (
                    <div className="max-w-[90%] sm:max-w-[80%] rounded-lg px-4 py-2.5 text-sm bg-[var(--primary)] text-[var(--primary-foreground)]">
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    </div>
                  ) : (
                    <div className="max-w-[90%] sm:max-w-[80%] rounded-lg px-4 py-2.5 text-sm bg-[var(--muted)] prose-chat">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  )}
                </div>
              ))}

              {waiting && <ThinkingIndicator />}

              {streaming && streamingDisplay && (
                <div className="flex justify-start">
                  <div className="max-w-[90%] sm:max-w-[80%] rounded-lg px-4 py-2.5 text-sm bg-[var(--muted)] prose-chat">
                    <ReactMarkdown>{streamingDisplay}</ReactMarkdown>
                    <span className="inline-block w-1.5 h-4 bg-[var(--foreground)] animate-pulse ml-0.5" />
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="p-3 border-t border-[var(--border)]">
              {/* Attached file chips */}
              {attachedFiles.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {attachedFiles.map((file, i) => (
                    <span
                      key={`${file.name}-${i}`}
                      className="inline-flex items-center gap-1 px-2 py-1 bg-[var(--muted)] rounded-md text-xs"
                    >
                      <svg className="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      <span className="truncate max-w-[120px]">{file.name}</span>
                      <button
                        onClick={() => removeFile(i)}
                        className="text-[var(--muted-foreground)] hover:text-[var(--destructive)] ml-0.5"
                      >
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <div className="flex gap-2 items-end">
                {/* Hidden file input */}
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".txt,.md,.csv,.json"
                  onChange={handleFileSelect}
                  className="hidden"
                />
                {/* Paperclip button */}
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isBusy || attachedFiles.length >= 3}
                  className="p-2 rounded-lg text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--muted)] disabled:opacity-50 flex-shrink-0 self-end"
                  title="Attach files (.txt, .md, .csv, .json)"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                  </svg>
                </button>
                <AutoResizeTextarea
                  value={input}
                  onChange={setInput}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask about this creator's content..."
                  disabled={isBusy}
                />
                <button
                  onClick={() => handleSend()}
                  disabled={isBusy || !input.trim()}
                  className="px-3 sm:px-4 py-2 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50 flex-shrink-0 self-end"
                >
                  {isBusy ? (
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                    </svg>
                  )}
                </button>
              </div>
              <p className="text-xs text-[var(--muted-foreground)] mt-1.5 hidden sm:block">
                Enter to send, Shift+Enter for new line. Attach .txt, .md, .csv, or .json files.
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center h-64">
          <p className="text-[var(--muted-foreground)]">Loading...</p>
        </div>
      }
    >
      <ChatInner />
    </Suspense>
  );
}
