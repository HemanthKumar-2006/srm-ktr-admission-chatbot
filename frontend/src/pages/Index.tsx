import { useState, useRef, useEffect } from "react";
import { Send, Bot, ExternalLink } from "lucide-react";
import FloatingOrbs from "@/components/FloatingOrbs";

interface Message {
  id: number;
  content: string;
  isUser: boolean;
  intent?: string;
  campus?: string | null;
  program?: string | null;
}

/**
 * Renders a markdown-like string into React elements.
 * Supports: **bold**, bullet points (•/-), headings (##), and [link](url).
 */
const renderMarkdown = (text: string) => {
  const lines = text.split("\n");

  return lines.map((line, i) => {
    // Heading lines
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

    // Empty lines
    if (line.trim() === "") return <br key={i} />;

    // Bullet points
    const isBullet =
      line.trimStart().startsWith("•") ||
      line.trimStart().startsWith("- ") ||
      line.trimStart().startsWith("* ");

    // Process inline formatting: **bold** and [text](url)
    const processInline = (str: string) => {
      const parts: (string | JSX.Element)[] = [];
      const regex = /(\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\))/g;
      let lastIndex = 0;
      let match;

      while ((match = regex.exec(str)) !== null) {
        if (match.index > lastIndex) {
          parts.push(str.slice(lastIndex, match.index));
        }

        if (match[2]) {
          // Bold
          parts.push(
            <strong key={match.index} className="font-semibold">
              {match[2]}
            </strong>
          );
        } else if (match[3] && match[4]) {
          // Link
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
      const bulletContent = line.trimStart().replace(/^[•\-\*]\s*/, "");
      return (
        <div key={i} className="flex gap-2 ml-1 my-0.5">
          <span className="text-primary mt-0.5">•</span>
          <span>{processInline(bulletContent)}</span>
        </div>
      );
    }

    return (
      <p key={i} className="my-0.5">
        {processInline(line)}
      </p>
    );
  });
};

const Index = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isTyping]);

  const handleSend = async () => {
    if (!input.trim() || isTyping) return;

    const userText = input.trim();

    const userMsg: Message = {
      id: Date.now(),
      content: userText,
      isUser: true,
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsTyping(true);

    try {
      const res = await fetch("http://127.0.0.1:8000/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: userText }),
      });

      const data = await res.json();

      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          content: data.response || "No response from server.",
          isUser: false,
          intent: data.intent,
          campus: data.campus,
          program: data.program,
        },
      ]);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          content: "⚠️ Cannot connect to SRM server. Please try again.",
          isUser: false,
        },
      ]);
    }

    setIsTyping(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const intentLabels: Record<string, string> = {
    fee_structure: "💰 Fees",
    admission_process: "📋 Admission",
    hostel_info: "🏠 Hostel",
    course_details: "📚 Courses",
    campus_life: "🎓 Campus",
    eligibility: "✅ Eligibility",
    general_query: "💬 General",
  };

  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden bg-background px-4">
      <FloatingOrbs />

      <div className="relative z-10 flex flex-col items-center w-full max-w-2xl">
        {/* Title */}
        <div className="text-center mb-6 animate-fade-slide-up">
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight leading-tight">
            <span className="gradient-text">SRM University</span>
            <br />
            <span className="text-foreground">Chatbot</span>
          </h1>
        </div>

        {/* Subtitle */}
        <p className="text-muted-foreground text-base sm:text-lg text-center max-w-md mb-10 animate-fade-slide-up">
          Ask anything about admissions, fees, courses, and campus.
        </p>

        {/* Messages */}
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
                    className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${msg.isUser
                        ? "gradient-primary text-primary-foreground"
                        : "glass text-foreground"
                      }`}
                  >
                    {msg.isUser ? msg.content : renderMarkdown(msg.content)}
                  </div>
                  {/* Intent badge for bot messages */}
                  {!msg.isUser && msg.intent && (
                    <span className="text-[10px] text-muted-foreground mt-1 px-2 opacity-60">
                      {intentLabels[msg.intent] || msg.intent}
                    </span>
                  )}
                </div>
              </div>
            ))}

            {isTyping && (
              <div className="flex justify-start">
                <div className="w-7 h-7 rounded-lg gradient-primary flex items-center justify-center mr-2 mt-1">
                  <Bot className="w-3.5 h-3.5 text-primary-foreground" />
                </div>
                <div className="glass rounded-2xl px-4 py-3 flex gap-1">
                  <span className="typing-dot w-2 h-2 rounded-full bg-muted-foreground" />
                  <span className="typing-dot w-2 h-2 rounded-full bg-muted-foreground" />
                  <span className="typing-dot w-2 h-2 rounded-full bg-muted-foreground" />
                </div>
              </div>
            )}
          </div>
        )}

        {/* Input */}
        <div className="w-full">
          <div className="glass-strong rounded-3xl p-1.5">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask me anything about SRM…"
                disabled={isTyping}
                className="flex-1 bg-transparent px-5 py-3.5 text-sm outline-none"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || isTyping}
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

export default Index;