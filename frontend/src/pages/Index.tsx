import { useState, useRef, useEffect } from "react";
import { Send, Bot, ExternalLink, MapPin, RefreshCw, CornerDownLeft } from "lucide-react";
import srmLogo from "@/assets/logo.png";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface Message {
  id: number;
  content: string;
  isUser: boolean;
  intent?: string;
  campus?: string | null;
  program?: string | null;
}

const SUGGESTION_SETS = [
  [
    "What are the B.Tech fees?",
    "How does SRM admission work?",
    "Tell me about hostel facilities",
    "What courses are available?",
  ],
  [
    "SRMJEEE exam details",
    "Scholarship opportunities",
    "Campus placement stats",
    "PhD admission process",
  ],
  [
    "Management quota seats",
    "NRI admission process",
    "Fee payment schedule",
    "Lateral entry eligibility",
  ],
];

/**
 * Renders markdown-like text to React elements.
 */
const renderMarkdown = (text: string) => {
  const lines = text.split("\n");
  return lines.map((line, i) => {
    if (line.startsWith("### ")) {
      return <h4 key={i} className="font-semibold text-sm mt-2 mb-1 text-gray-800">{line.replace("### ", "")}</h4>;
    }
    if (line.startsWith("## ")) {
      return <h3 key={i} className="font-bold text-sm mt-3 mb-1 text-gray-900">{line.replace("## ", "")}</h3>;
    }
    if (line.trim() === "") return <br key={i} />;

    const isBullet =
      line.trimStart().startsWith("•") ||
      line.trimStart().startsWith("- ") ||
      line.trimStart().startsWith("* ");

    const processInline = (str: string) => {
      const parts: (string | JSX.Element)[] = [];
      const regex = /(\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\))/g;
      let lastIndex = 0;
      let match;
      while ((match = regex.exec(str)) !== null) {
        if (match.index > lastIndex) parts.push(str.slice(lastIndex, match.index));
        if (match[2]) {
          parts.push(<strong key={match.index} className="font-semibold">{match[2]}</strong>);
        } else if (match[3] && match[4]) {
          parts.push(
            <a key={match.index} href={match[4]} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-blue-600 hover:underline">
              {match[3]}<ExternalLink className="w-3 h-3 inline" />
            </a>
          );
        }
        lastIndex = match.index + match[0].length;
      }
      if (lastIndex < str.length) parts.push(str.slice(lastIndex));
      return parts;
    };

    if (isBullet) {
      const bulletContent = line.trimStart().replace(/^[•\-\*]\s*/, "");
      return (
        <div key={i} className="flex gap-2 ml-1 my-0.5">
          <span className="text-blue-500 mt-0.5">•</span>
          <span>{processInline(bulletContent)}</span>
        </div>
      );
    }
    return <p key={i} className="my-0.5">{processInline(line)}</p>;
  });
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

const Index = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [selectedCampus, setSelectedCampus] = useState("KTR");
  const [suggestionSet, setSuggestionSet] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const isWelcome = messages.length === 0;

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isTyping]);

  const handleSend = async (text?: string) => {
    const userText = (text ?? input).trim();
    if (!userText || isTyping) return;

    const userMsg: Message = { id: Date.now(), content: userText, isUser: true };
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
    } catch {
      setMessages((prev) => [
        ...prev,
        { id: Date.now() + 1, content: "⚠️ Cannot connect to SRM server. Please try again.", isUser: false },
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

  const refreshSuggestions = () => {
    setSuggestionSet((prev) => (prev + 1) % SUGGESTION_SETS.length);
  };

  const currentSuggestions = SUGGESTION_SETS[suggestionSet];

  return (
    <div
      className="min-h-screen flex flex-col"
      style={{
        background: "linear-gradient(160deg, #e0e7ff 0%, #dbeafe 35%, #f0f9ff 65%, #ffffff 100%)",
      }}
    >
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 z-20">
        <div className="flex items-center gap-2">
          <img src={srmLogo} alt="SRM Logo" className="h-10 w-auto object-contain" />
        </div>
        <Select value={selectedCampus} onValueChange={setSelectedCampus}>
          <SelectTrigger className="w-[190px] bg-white/70 backdrop-blur-md border border-gray-200 shadow-sm rounded-xl text-sm font-medium text-gray-700">
            <div className="flex items-center gap-2">
              <MapPin className="w-4 h-4 text-blue-500 shrink-0" />
              <SelectValue placeholder="Select Branch" />
            </div>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="KTR">Kattankulathur</SelectItem>
            <SelectItem value="Ramapuram">Ramapuram</SelectItem>
            <SelectItem value="Vadapalani">Vadapalani</SelectItem>
            <SelectItem value="Ghaziabad">Delhi-NCR (Ghaziabad)</SelectItem>
            <SelectItem value="Tiruchirappalli">Tiruchirappalli</SelectItem>
          </SelectContent>
        </Select>
      </header>

      {/* Main content area */}
      <div className="flex-1 flex flex-col items-center px-4 pb-4 min-h-0">
        {isWelcome ? (
          /* ── Welcome State ── */
          <div className="flex flex-col items-center justify-center flex-1 w-full max-w-2xl gap-6">
            {/* Bot avatar orb */}
            <div
              className="w-16 h-16 rounded-full shadow-lg"
              style={{
                background: "radial-gradient(circle at 35% 30%, #60a5fa, #2563eb 50%, #1e3a8a)",
              }}
            />

            {/* Greeting */}
            <div className="text-center">
              <h1 className="text-4xl font-bold text-gray-900 leading-tight">
                Hello! I'm your SRM guide.
              </h1>
              <h2 className="text-3xl font-bold text-gray-900 mt-1">
                How can I help you today?
              </h2>
              <p className="text-gray-500 text-sm mt-3">
                Choose a prompt below or write your own to start chatting.
              </p>
            </div>

            {/* Suggestion chips */}
            <div className="w-full space-y-3">
              <div className="grid grid-cols-2 gap-2.5">
                {currentSuggestions.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => handleSend(s)}
                    className="text-left px-4 py-3 rounded-xl bg-white/80 border border-gray-200 text-sm text-gray-700 font-medium hover:bg-white hover:border-blue-300 hover:shadow-sm transition-all duration-150"
                  >
                    {s}
                  </button>
                ))}
              </div>
              <button
                onClick={refreshSuggestions}
                className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors pl-1"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Refresh prompts
              </button>
            </div>

            {/* Input box */}
            <div className="w-full">
              <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask me anything about SRM…"
                  rows={2}
                  className="w-full resize-none px-5 pt-4 pb-2 text-sm text-gray-800 placeholder-gray-400 outline-none bg-transparent leading-relaxed"
                />
                <div className="flex items-center justify-between px-5 pb-3">
                  <span className="text-xs text-gray-400 font-medium">SRM Admission Bot · {selectedCampus}</span>
                  <button
                    onClick={() => handleSend()}
                    disabled={!input.trim() || isTyping}
                    className="w-8 h-8 flex items-center justify-center rounded-lg bg-blue-600 text-white disabled:opacity-30 hover:bg-blue-700 transition-colors"
                  >
                    <Send className="w-4 h-4" />
                  </button>
                </div>
              </div>
              <p className="text-center text-xs text-gray-400 mt-2">
                This bot may make mistakes. Double-check important information.&nbsp; &nbsp;
                Use <kbd className="px-1 py-0.5 rounded bg-gray-100 text-gray-500 font-mono text-[10px]">Shift</kbd>+<kbd className="px-1 py-0.5 rounded bg-gray-100 text-gray-500 font-mono text-[10px]">Enter</kbd> for new line
              </p>
            </div>
          </div>
        ) : (
          /* ── Chat State ── */
          <div className="flex flex-col w-full max-w-2xl flex-1 min-h-0 gap-4">
            {/* Messages */}
            <div
              ref={scrollRef}
              className="flex-1 overflow-y-auto space-y-4 py-4 scroll-smooth"
              style={{ minHeight: 0 }}
            >
              {messages.map((msg) => (
                <div key={msg.id} className={`flex ${msg.isUser ? "justify-end" : "justify-start"} items-end gap-2`}>
                  {!msg.isUser && (
                    <div
                      className="w-7 h-7 rounded-full shrink-0 mb-1"
                      style={{
                        background: "radial-gradient(circle at 35% 30%, #a78bfa, #6d28d9 50%, #312e81)",
                      }}
                    />
                  )}
                  <div className="max-w-[80%] flex flex-col">
                    <div
                      className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                        msg.isUser
                          ? "bg-blue-100 text-gray-900 rounded-br-sm"
                          : "bg-white text-gray-900 shadow-sm border border-gray-100 rounded-bl-sm"
                      }`}
                    >
                      {msg.isUser ? msg.content : renderMarkdown(msg.content)}
                    </div>
                    {!msg.isUser && msg.intent && (
                      <span className="text-[10px] text-gray-400 mt-1 px-2">
                        {intentLabels[msg.intent] || msg.intent}
                      </span>
                    )}
                  </div>
                </div>
              ))}

              {isTyping && (
                <div className="flex items-end gap-2 justify-start">
                  <div
                    className="w-7 h-7 rounded-full shrink-0 mb-1"
                    style={{
                      background: "radial-gradient(circle at 35% 30%, #60a5fa, #2563eb 50%, #1e3a8a)",
                    }}
                  />
                  <div className="bg-white border border-gray-100 shadow-sm rounded-2xl rounded-bl-sm px-4 py-3 flex gap-1.5">
                    <span className="typing-dot w-2 h-2 rounded-full bg-gray-400" />
                    <span className="typing-dot w-2 h-2 rounded-full bg-gray-400" />
                    <span className="typing-dot w-2 h-2 rounded-full bg-gray-400" />
                  </div>
                </div>
              )}
            </div>

            {/* Chat input */}
            <div className="shrink-0">
              <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask a follow-up question…"
                  rows={2}
                  className="w-full resize-none px-5 pt-4 pb-2 text-sm text-gray-800 placeholder-gray-400 outline-none bg-transparent leading-relaxed"
                />
                <div className="flex items-center justify-between px-5 pb-3">
                  <span className="text-xs text-gray-400 font-medium">SRM Admission Bot · {selectedCampus}</span>
                  <button
                    onClick={() => handleSend()}
                    disabled={!input.trim() || isTyping}
                    className="w-8 h-8 flex items-center justify-center rounded-lg bg-blue-600 text-white disabled:opacity-30 hover:bg-blue-700 transition-colors"
                  >
                    <Send className="w-4 h-4" />
                  </button>
                </div>
              </div>
              <p className="text-center text-xs text-gray-400 mt-2">
                This bot may make mistakes. Double-check important information.&nbsp; &nbsp;
                Use <kbd className="px-1 py-0.5 rounded bg-gray-100 text-gray-500 font-mono text-[10px]">Shift</kbd>+<kbd className="px-1 py-0.5 rounded bg-gray-100 text-gray-500 font-mono text-[10px]">Enter</kbd> for new line
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default Index;