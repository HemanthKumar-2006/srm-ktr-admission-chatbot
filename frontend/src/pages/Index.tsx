import { useState, useRef, useEffect } from "react";
import { Send, ExternalLink, MapPin, RefreshCw, Plus } from "lucide-react";
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
  sources?: ApiSource[];
}

interface ApiSource {
  index?: number;
  title?: string;
  url?: string;
}

interface ChatApiResponse {
  response?: string;
  sources?: unknown;
  intent?: string;
  campus?: string | null;
  program?: string | null;
}

const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const SRM_LOGO = "/srm-logo.png";

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

const normalizeSources = (sources: unknown): ApiSource[] => {
  if (!Array.isArray(sources)) return [];

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

const stripInlineSourcesBlock = (text: string): string => {
  if (!text) return text;
  const normalized = text.replace(/\r\n/g, "\n");
  let cleaned = normalized;

  cleaned = cleaned.replace(/(?:\n|^)\s*\*{0,2}sources?\*{0,2}\s*:\s*[\s\S]*$/i, "");
  cleaned = cleaned.replace(/\s+\*{0,2}sources?\*{0,2}\s*:\s*https?:\/\/\S+\s*$/i, "");
  cleaned = cleaned.replace(/\s+\*{0,2}sources?\*{0,2}\s*:\s*(?:\[[^\]]+\]\([^)]+\)|\[\d+\]|https?:\/\/\S+|,\s*)+\s*$/i, "");

  const fallbackRe = /[\n\r]*\s*I don[''\u2019]?t have (?:enough |specific |)?information.*?(?:contact\s+(?:the\s+)?(?:SRM\s+)?admissions|srmist\.edu\.in)[.!]?\s*/gis;
  const candidate = cleaned.replace(fallbackRe, "").trim();
  if (candidate.length >= 40) {
    cleaned = candidate;
  }

  return cleaned.trim();
};

const renderMarkdown = (text: string, sources: ApiSource[] = []) => {
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
      const regex = /(\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\)|\[(\d+)\]|(https?:\/\/[^\s)]+))/g;
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
        } else if (match[5]) {
          const citationIndex = Number(match[5]);
          const source = sources[citationIndex - 1];
          if (source?.url) {
            parts.push(
              <a
                key={match.index}
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-blue-600 hover:underline"
              >
                [{citationIndex}]<ExternalLink className="w-3 h-3 inline" />
              </a>
            );
          } else {
            parts.push(`[${citationIndex}]`);
          }
        } else if (match[6]) {
          parts.push(
            <a
              key={match.index}
              href={match[6]}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-blue-600 hover:underline break-all"
            >
              {match[6]}
              <ExternalLink className="w-3 h-3 inline" />
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
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: userText }),
      });
      const data: ChatApiResponse = await res.json();
      const cleanedResponse = stripInlineSourcesBlock(data.response || "No response from server.");
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          content: cleanedResponse,
          isUser: false,
          intent: data.intent,
          campus: data.campus,
          program: data.program,
          sources: normalizeSources(data.sources),
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { id: Date.now() + 1, content: "Cannot connect to SRM server. Please try again.", isUser: false },
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

  const handleNewChat = () => {
    setMessages([]);
    setInput("");
    setIsTyping(false);
  };

  const currentSuggestions = SUGGESTION_SETS[suggestionSet];

  return (
    <div className="relative h-screen overflow-hidden">
      <div
        className="absolute inset-0 -z-10"
        style={{
          background: "linear-gradient(160deg, #cfd9ff 0%, #c8dcff 35%, #e8f3ff 68%, #f4f9ff 100%)",
        }}
      />
      <header className="fixed top-0 left-0 right-0 flex items-start justify-between px-6 py-4 z-20">
        <div className="flex flex-col gap-2">
          <a
            href="https://www.srmist.edu.in"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center rounded-xl bg-white/70 backdrop-blur-md border border-gray-200 shadow-sm px-3 py-2 hover:bg-white/80 transition-colors"
            aria-label="Open SRM official website"
          >
            <img src={SRM_LOGO} alt="SRM Logo" className="h-8 w-auto object-contain" />
          </a>
          <button
            onClick={handleNewChat}
            className="inline-flex items-center gap-2 rounded-xl bg-white/70 backdrop-blur-md border border-gray-200 shadow-sm px-3 py-2 text-sm font-medium text-gray-700 hover:bg-white/80 transition-colors w-fit"
          >
            <Plus className="w-4 h-4 text-blue-500" />
            New chat
          </button>
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

      <div className="h-full flex flex-col items-center px-4 pb-4 pt-28 min-h-0 overflow-hidden">
        {isWelcome ? (
          <div className="flex flex-col items-center justify-center flex-1 w-full max-w-2xl gap-6">
            <div
              className="w-16 h-16 rounded-full shadow-lg"
              style={{
                background: "radial-gradient(circle at 35% 30%, #60a5fa, #2563eb 50%, #1e3a8a)",
              }}
            />

            <div className="text-center">
              <h1 className="text-4xl font-bold text-gray-900 leading-tight">
                Hello! I&apos;m your SRM guide.
              </h1>
              <h2 className="text-3xl font-bold text-gray-900 mt-1">
                How can I help you today?
              </h2>
              <p className="text-gray-500 text-sm mt-3">
                Choose a prompt below or write your own to start chatting.
              </p>
            </div>

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

            <div className="w-full">
              <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask me anything about SRM..."
                  rows={2}
                  className="w-full resize-none px-5 pt-4 pb-2 text-sm text-gray-800 placeholder-gray-400 outline-none bg-transparent leading-relaxed"
                />
                <div className="flex items-center justify-between px-5 pb-3">
                  <span className="text-xs text-gray-400 font-medium">SRM Admission Bot - {selectedCampus}</span>
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
                This bot may make mistakes. Double-check important information.&nbsp;&nbsp;
                Use <kbd className="px-1 py-0.5 rounded bg-gray-100 text-gray-500 font-mono text-[10px]">Shift</kbd>+<kbd className="px-1 py-0.5 rounded bg-gray-100 text-gray-500 font-mono text-[10px]">Enter</kbd> for new line
              </p>
            </div>
          </div>
        ) : (
          <div className="flex flex-col w-full max-w-2xl flex-1 min-h-0">
            <div className="relative flex-1 min-h-0">
              <div
                ref={scrollRef}
                className="h-full overflow-y-auto no-scrollbar space-y-4 py-4 scroll-smooth"
              >
              {messages.map((msg) => (
                <div key={msg.id} className={`flex flex-col ${msg.isUser ? "items-end" : "items-start"}`}>
                  <div className={`flex ${msg.isUser ? "justify-end" : "justify-start"} items-end gap-2 w-full`}>
                    {!msg.isUser && (
                      <div
                        className="w-7 h-7 rounded-full shrink-0 mb-1"
                        style={{
                          background: "radial-gradient(circle at 35% 30%, #60a5fa, #2563eb 50%, #1e3a8a)",
                        }}
                      />
                    )}
                    <div
                      className={`max-w-[80%] px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                        msg.isUser
                          ? "bg-blue-50 text-gray-900 rounded-br-sm"
                          : "bg-white text-gray-900 shadow-sm border border-gray-100 rounded-bl-sm"
                      }`}
                    >
                      {msg.isUser ? msg.content : renderMarkdown(msg.content, msg.sources)}
                    </div>
                  </div>
                  {!msg.isUser && msg.sources && msg.sources.length > 0 && (
                    <details className="mt-2 px-2 group ml-9 max-w-[80%]">
                      <summary className="cursor-pointer list-none text-[11px] text-gray-500 hover:text-gray-700 select-none inline-flex items-center gap-1">
                        <span className="inline-block transition-transform group-open:rotate-90">▶</span>
                        Sources ({msg.sources.length})
                      </summary>
                      <div className="mt-2 space-y-1">
                        {msg.sources.map((source, index) => (
                          <a
                            key={`${msg.id}-source-${index}`}
                            href={source.url || "#"}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block truncate text-xs text-blue-600 hover:underline"
                          >
                            [{index + 1}] {source.title || source.url || `Source ${index + 1}`}
                          </a>
                        ))}
                      </div>
                    </details>
                  )}
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
            </div>

            <div className="shrink-0 pt-2">
              <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask a follow-up question..."
                  rows={2}
                  className="w-full resize-none px-5 pt-4 pb-2 text-sm text-gray-800 placeholder-gray-400 outline-none bg-transparent leading-relaxed"
                />
                <div className="flex items-center justify-between px-5 pb-3">
                  <span className="text-xs text-gray-400 font-medium">SRM Admission Bot - {selectedCampus}</span>
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
                This bot may make mistakes. Double-check important information.&nbsp;&nbsp;
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
