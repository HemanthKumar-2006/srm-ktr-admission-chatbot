import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Bot, ExternalLink, Send } from "lucide-react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import FloatingOrbs from "@/components/FloatingOrbs";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

interface ApiSource {
  index?: number;
  title?: string;
  url?: string;
}

interface Message {
  id: number;
  content: string;
  isUser: boolean;
  sources?: ApiSource[];
}

interface ChatApiResponse {
  response?: string;
  sources?: unknown;
  detail?: string;
}

const normalizeSources = (sources: unknown): ApiSource[] => {
  if (!Array.isArray(sources)) {
    return [];
  }

  return sources
    .map((source, index) => {
      if (typeof source === "string") {
        return {
          index: index + 1,
          title: source,
          url: source,
        };
      }

      if (source && typeof source === "object") {
        const item = source as ApiSource;
        return {
          index: item.index ?? index + 1,
          title: item.title ?? item.url ?? `Source ${index + 1}`,
          url: item.url,
        };
      }

      return null;
    })
    .filter((source): source is ApiSource => Boolean(source));
};

const renderMarkdown = (text: string) => {
  const lines = text.split("\n");

  return lines.map((line, i) => {
    if (line.startsWith("### ")) {
      return (
        <h4 key={i} className="font-semibold text-sm mt-2 mb-1 text-foreground/90">
          {line.replace("### ", "")}
        </h4>
      );
    }

    if (line.startsWith("## ")) {
      return (
        <h3 key={i} className="font-bold text-sm mt-3 mb-1 text-foreground">
          {line.replace("## ", "")}
        </h3>
      );
    }

    if (line.trim() === "") {
      return <br key={i} />;
    }

    const trimmed = line.trimStart();
    const isBullet =
      trimmed.startsWith("•") ||
      trimmed.startsWith("- ") ||
      trimmed.startsWith("* ");

    const processInline = (str: string) => {
      const parts: ReactNode[] = [];
      const regex = /(\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\))/g;
      let lastIndex = 0;
      let match: RegExpExecArray | null;

      while ((match = regex.exec(str)) !== null) {
        if (match.index > lastIndex) {
          parts.push(str.slice(lastIndex, match.index));
        }

        if (match[2]) {
          parts.push(
            <strong key={match.index} className="font-semibold">
              {match[2]}
            </strong>
          );
        } else if (match[3] && match[4]) {
          parts.push(
            <a
              key={match.index}
              href={match[4]}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline transition-colors"
            >
              {match[3]}
              <ExternalLink className="w-3 h-3 inline" />
            </a>
          );
        }

        lastIndex = match.index + match[0].length;
      }

      if (lastIndex < str.length) {
        parts.push(str.slice(lastIndex));
      }

      return parts;
    };

    if (isBullet) {
      const bulletContent = trimmed.replace(/^(•|\-|\*)\s*/, "");
      return (
        <div key={i} className="flex gap-2 ml-1 my-0.5">
          <span className="text-primary mt-0.5">-</span>
          <span>{processInline(bulletContent)}</span>
        </div>
      );
    }

    return (
      <p key={i} className="my-0.5 whitespace-pre-wrap">
        {processInline(line)}
      </p>
    );
  });
};

const ChatPage = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const handleSend = async () => {
    if (!input.trim() || loading) {
      return;
    }

    const userMessage = input.trim();

    setMessages((prev) => [
      ...prev,
      {
        id: Date.now(),
        content: userMessage,
        isUser: true,
      },
    ]);
    setInput("");
    setLoading(true);

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query: userMessage,
        }),
      });

      const data: ChatApiResponse = await response.json().catch(() => ({}));

      if (!response.ok) {
        const detail =
          typeof data.detail === "string" && data.detail.trim()
            ? data.detail
            : `Request failed with status ${response.status}.`;
        throw new Error(detail);
      }

      const botReply =
        typeof data.response === "string" && data.response.trim()
          ? data.response
          : "The server returned an empty response.";

      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          content: botReply,
          isUser: false,
          sources: normalizeSources(data.sources),
        },
      ]);
    } catch (error) {
      console.error("API ERROR:", error);

      const errorMessage =
        error instanceof Error && error.message.trim()
          ? error.message
          : "Unable to reach the chatbot server at http://localhost:8000.";

      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          content: errorMessage,
          isUser: false,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden bg-background px-4">
      <FloatingOrbs />

      <div className="relative z-10 flex flex-col items-center w-full max-w-2xl">
        <div className="text-center mb-6 animate-fade-slide-up">
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight leading-tight">
            <span className="gradient-text">SRM University</span>
            <br />
            <span className="text-foreground">Chatbot</span>
          </h1>
        </div>

        <p className="text-muted-foreground text-base sm:text-lg text-center max-w-md mb-10 animate-fade-slide-up">
          Ask anything about admissions, fees, courses, and campus.
        </p>

        {messages.length > 0 && (
          <div
            ref={scrollRef}
            className="w-full max-h-[50vh] overflow-y-auto space-y-3 mb-6 px-1 scroll-smooth"
          >
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex ${msg.isUser ? "justify-end" : "justify-start"}`}
              >
                {!msg.isUser && (
                  <div className="w-7 h-7 rounded-lg gradient-primary flex items-center justify-center mr-2 mt-1 flex-shrink-0">
                    <Bot className="w-3.5 h-3.5 text-primary-foreground" />
                  </div>
                )}

                <div className="max-w-[85%] flex flex-col">
                  <div
                    className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
                      msg.isUser
                        ? "gradient-primary text-primary-foreground"
                        : "glass text-foreground"
                    }`}
                  >
                    {msg.isUser ? (
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    ) : (
                      renderMarkdown(msg.content)
                    )}
                  </div>

                  {!msg.isUser && msg.sources && msg.sources.length > 0 && (
                    <div className="mt-2 space-y-1 px-2">
                      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                        Sources
                      </p>
                      {msg.sources.map((source, index) => (
                        <a
                          key={`${msg.id}-source-${index}`}
                          href={source.url || "#"}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block truncate text-xs text-primary hover:underline"
                        >
                          {source.title || source.url || `Source ${index + 1}`}
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex justify-start">
                <div className="w-7 h-7 rounded-lg gradient-primary flex items-center justify-center mr-2 mt-1">
                  <Bot className="w-3.5 h-3.5 text-primary-foreground" />
                </div>
                <div className="glass rounded-2xl px-4 py-3 text-sm text-muted-foreground">
                  Thinking...
                </div>
              </div>
            )}
          </div>
        )}

        <div className="w-full">
          <div className="glass-strong rounded-3xl p-1.5">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask me anything about SRM..."
                disabled={loading}
                className="flex-1 bg-transparent px-5 py-3.5 text-sm outline-none"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || loading}
                className="w-10 h-10 flex items-center justify-center rounded-2xl gradient-primary text-primary-foreground disabled:opacity-30"
              >
                <Send className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
