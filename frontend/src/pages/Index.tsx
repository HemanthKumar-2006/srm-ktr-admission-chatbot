import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Bot, ExternalLink, GraduationCap, Send } from "lucide-react";
import FloatingOrbs from "@/components/FloatingOrbs";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

interface Source {
  index: number;
  title: string;
  url: string;
}

interface Message {
  id: number;
  content: string;
  isUser: boolean;
  sources?: Source[];
}

// ── Helpers ────────────────────────────────────────────────────────────────

const normalizeSources = (raw: unknown): Source[] => {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((s, i) => {
      if (typeof s === "string") return { index: i + 1, title: s, url: s };
      if (s && typeof s === "object") {
        const item = s as Record<string, unknown>;
        return {
          index: typeof item.index === "number" ? item.index : i + 1,
          title: typeof item.title === "string" ? item.title : (typeof item.url === "string" ? item.url : `Source ${i + 1}`),
          url: typeof item.url === "string" ? item.url : "#",
        };
      }
      return null;
    })
    .filter((s): s is Source => s !== null);
};

// Renders **bold**, - bullets, ## headings, and [link](url)
const renderMarkdown = (text: string): ReactNode[] => {
  const processInline = (str: string, key: string): ReactNode[] => {
    const parts: ReactNode[] = [];
    const re = /(\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\))/g;
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(str)) !== null) {
      if (m.index > last) parts.push(str.slice(last, m.index));
      if (m[2]) {
        parts.push(<strong key={`${key}-b${m.index}`} className="font-semibold">{m[2]}</strong>);
      } else if (m[3] && m[4]) {
        parts.push(
          <a key={`${key}-a${m.index}`} href={m[4]} target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center gap-0.5 text-primary hover:underline">
            {m[3]}<ExternalLink className="w-3 h-3" />
          </a>
        );
      }
      last = m.index + m[0].length;
    }
    if (last < str.length) parts.push(str.slice(last));
    return parts;
  };

  return text.split("\n").map((line, i) => {
    if (line.startsWith("## "))  return <h3 key={i} className="font-bold text-sm mt-3 mb-1 text-foreground">{line.slice(3)}</h3>;
    if (line.startsWith("### ")) return <h4 key={i} className="font-semibold text-sm mt-2 mb-0.5 text-foreground">{line.slice(4)}</h4>;
    if (line.trim() === "")      return <br key={i} />;

    const trimmed = line.trimStart();
    const isBullet = trimmed.startsWith("- ") || trimmed.startsWith("• ") || trimmed.startsWith("* ");
    if (isBullet) {
      return (
        <div key={i} className="flex gap-2 my-0.5 ml-1">
          <span className="text-primary flex-shrink-0 mt-0.5">•</span>
          <span>{processInline(trimmed.replace(/^[-•*]\s*/, ""), `${i}`)}</span>
        </div>
      );
    }
    return <p key={i} className="my-0.5">{processInline(line, `${i}`)}</p>;
  });
};

// ── Suggested prompts shown on first load ──────────────────────────────────

const SUGGESTIONS = [
  "What are the B.Tech admission requirements?",
  "What is the fee structure for CSE?",
  "How do I apply for SRMJEEE?",
  "What hostel facilities are available at KTR?",
];

// ── Component ──────────────────────────────────────────────────────────────

const Index = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const sendMessage = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    setMessages((prev) => [...prev, { id: Date.now(), content: trimmed, isUser: true }]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: trimmed }),
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
      }

      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          content: typeof data.response === "string" && data.response.trim()
            ? data.response
            : "No response received.",
          isUser: false,
          sources: normalizeSources(data.sources),
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          content: err instanceof Error ? err.message : "Could not reach the server. Is the backend running?",
          isUser: false,
        },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  return (
    <div className="relative flex flex-col h-screen overflow-hidden bg-background">
      <FloatingOrbs />

      {/* ── Header ── */}
      <header className="relative z-10 flex items-center gap-3 px-6 py-4 border-b border-border/60 glass-strong flex-shrink-0">
        <div className="w-10 h-10 rounded-xl gradient-primary flex items-center justify-center glow-sm flex-shrink-0">
          <GraduationCap className="w-5 h-5 text-primary-foreground" />
        </div>
        <div>
          <h1 className="text-base font-bold text-foreground leading-tight">SRM KTR Admission Assistant</h1>
          <p className="text-xs text-muted-foreground flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
            Powered by RAG · KTR Campus
          </p>
        </div>
      </header>

      {/* ── Chat area ── */}
      <main className="relative z-10 flex-1 overflow-y-auto px-4 py-6 scroll-smooth" ref={scrollRef}>
        {messages.length === 0 ? (
          /* Welcome / suggestions */
          <div className="flex flex-col items-center justify-center min-h-full gap-8 text-center animate-fade-slide-up">
            <div className="space-y-2">
              <div className="w-16 h-16 rounded-2xl gradient-primary flex items-center justify-center mx-auto glow-sm">
                <Bot className="w-8 h-8 text-primary-foreground" />
              </div>
              <h2 className="text-2xl font-bold text-foreground">Hi, I'm your SRM Advisor</h2>
              <p className="text-muted-foreground text-sm max-w-xs mx-auto">
                Ask me anything about admissions, fees, courses, or campus life at SRM KTR.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-lg">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => sendMessage(s)}
                  className="glass text-left text-sm px-4 py-3 rounded-xl hover:bg-primary/5 hover:border-primary/30 transition-all text-foreground/80 hover:text-foreground"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* Messages */
          <div className="max-w-2xl mx-auto space-y-5">
            {messages.map((msg) => (
              <div key={msg.id} className={`flex gap-3 ${msg.isUser ? "flex-row-reverse" : "flex-row"}`}>
                {!msg.isUser && (
                  <div className="w-8 h-8 rounded-lg gradient-primary flex items-center justify-center flex-shrink-0 mt-1">
                    <Bot className="w-4 h-4 text-primary-foreground" />
                  </div>
                )}

                <div className={`flex flex-col max-w-[80%] ${msg.isUser ? "items-end" : "items-start"}`}>
                  <div
                    className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                      msg.isUser
                        ? "gradient-primary text-primary-foreground rounded-br-sm"
                        : "glass text-foreground rounded-bl-sm"
                    }`}
                  >
                    {msg.isUser
                      ? <p className="whitespace-pre-wrap">{msg.content}</p>
                      : renderMarkdown(msg.content)
                    }
                  </div>

                  {!msg.isUser && msg.sources && msg.sources.length > 0 && (
                    <div className="mt-2 px-1 space-y-1">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">Sources</p>
                      {msg.sources.map((src) => (
                        <a
                          key={src.index}
                          href={src.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-1 text-xs text-primary hover:underline truncate max-w-xs"
                        >
                          <ExternalLink className="w-3 h-3 flex-shrink-0" />
                          {src.title !== src.url ? src.title : (() => { try { return new URL(src.url).hostname; } catch { return src.url; } })()}
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {/* Typing indicator */}
            {loading && (
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-lg gradient-primary flex items-center justify-center flex-shrink-0 mt-1">
                  <Bot className="w-4 h-4 text-primary-foreground" />
                </div>
                <div className="glass px-4 py-3 rounded-2xl rounded-bl-sm flex items-center gap-1.5">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="typing-dot w-1.5 h-1.5 rounded-full bg-muted-foreground/60"
                      style={{ animationDelay: `${i * 0.2}s` }}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      {/* ── Input bar ── */}
      <div className="relative z-10 px-4 pb-5 pt-3 flex-shrink-0">
        <div className="max-w-2xl mx-auto">
          <div className="glass-strong rounded-2xl p-1.5 flex items-end gap-2">
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                e.target.style.height = "auto";
                e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
              }}
              onKeyDown={handleKeyDown}
              placeholder="Ask me anything about SRM KTR admissions..."
              disabled={loading}
              className="flex-1 bg-transparent px-4 py-2.5 text-sm outline-none resize-none max-h-[120px] leading-relaxed placeholder:text-muted-foreground disabled:opacity-50"
              style={{ height: "40px" }}
            />
            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || loading}
              className="w-10 h-10 flex items-center justify-center rounded-xl gradient-primary text-primary-foreground disabled:opacity-30 hover:opacity-90 transition-opacity flex-shrink-0 mb-0.5 glow-sm disabled:shadow-none"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
          <p className="text-center text-[10px] text-muted-foreground mt-2">
            Answers are based on official SRM website content · Always verify at{" "}
            <a href="https://www.srmist.edu.in" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
              srmist.edu.in
            </a>
          </p>
        </div>
      </div>
    </div>
  );
};

export default Index;
