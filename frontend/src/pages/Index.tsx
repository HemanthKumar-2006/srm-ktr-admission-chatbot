import { useState, useRef, useEffect } from "react";
import { Send, ExternalLink, MapPin, RefreshCw, Plus, Pin, X, Info } from "lucide-react";
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
  confidence?: number | null;
  queryMetadata?: QueryMetadata | null;
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
  confidence?: number | null;
  query_metadata?: QueryMetadata | null;
}

interface QueryMetadata {
  domain?: string | null;
  task?: string | null;
  routing_target?: string | null;
  confidence?: number | null;
  entities?: Record<string, unknown>;
  freshness?: string | null;
  used_pinned_context?: boolean;
  decomposed?: boolean;
}

interface PinnedContext {
  type: "campus" | "program" | "department";
  value: string;
  entityId?: string | null;
  displayName?: string | null;
}

const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const SRM_LOGO = "/srm-logo.png";
const CAMPUS_LABELS: Record<string, string> = {
  KTR: "Kattankulathur",
  Ramapuram: "Ramapuram",
  Vadapalani: "Vadapalani",
  "Delhi-NCR": "Delhi-NCR (Ghaziabad)",
  Tiruchirappalli: "Tiruchirappalli",
};

const SUGGESTION_SETS = [
  [
    "What are the B.Tech fees?",
    "How does SRM admission work?",
    "Tell me about hostel facilities",
    "What courses are available?",
  ],
  [
    "SRMJEEE exam details",
    "What scholarship opportunities are available for SRMIST students?",
    "What are the campus placement statistics for SRMIST?",
    "What is the PhD admission process at SRMIST?",
  ],
  [
    "How can I apply for management quota seats at SRMIST?",
    "What is the NRI admission process at SRMIST?",
    "When and how should B.Tech fees be paid during admission?",
    "What are the eligibility criteria for lateral entry into B.Tech at SRMIST?",
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

const formatMetadataValue = (value: unknown): string => {
  if (Array.isArray(value)) return value.map((item) => String(item)).join(", ");
  if (value == null) return "";
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const preferred =
      record.display_name ??
      record.name ??
      record.value ??
      record.label ??
      record.id;
    if (preferred != null) return String(preferred);
    try {
      return JSON.stringify(record);
    } catch {
      return String(record);
    }
  }
  return String(value);
};

const normalizePinnedContext = (context: PinnedContext | null) => {
  if (!context) return undefined;
  return {
    type: context.type,
    value: context.value,
    entity_id: context.entityId ?? undefined,
    display_name: context.displayName ?? undefined,
  };
};

const buildPinnedContextFromEntity = (
  type: PinnedContext["type"],
  value: unknown,
): PinnedContext | null => {
  const displayValue = formatMetadataValue(value).trim();
  if (!displayValue) return null;

  if (typeof value === "object" && value != null && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    return {
      type,
      value: String(record.value ?? record.name ?? record.display_name ?? displayValue),
      entityId: record.id != null ? String(record.id) : null,
      displayName: displayValue,
    };
  }

  return {
    type,
    value: displayValue,
    displayName: displayValue,
  };
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
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const [pinnedContext, setPinnedContext] = useState<PinnedContext | null>(null);
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
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 120_000);
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: userText,
          campus: selectedCampus,
          session_id: sessionId,
          pinned_context: normalizePinnedContext(pinnedContext),
        }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      if (!res.ok) {
        throw new Error(`Server error: ${res.status}`);
      }
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
          confidence: data.confidence,
          queryMetadata: data.query_metadata,
        },
      ]);
    } catch (err) {
      const message =
        err instanceof DOMException && err.name === "AbortError"
          ? "The request timed out. The server may be busy — please try again."
          : "Cannot connect to SRM server. Please try again.";
      setMessages((prev) => [
        ...prev,
        { id: Date.now() + 1, content: message, isUser: false },
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
    setSessionId(crypto.randomUUID());
    setPinnedContext(null);
  };

  const handlePinContext = (context: PinnedContext) => {
    setPinnedContext(context);
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
        <div className="flex flex-col items-end gap-2">
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
              <SelectItem value="Delhi-NCR">Delhi-NCR (Ghaziabad)</SelectItem>
              <SelectItem value="Tiruchirappalli">Tiruchirappalli</SelectItem>
            </SelectContent>
          </Select>
          <button
            onClick={() =>
              handlePinContext({
                type: "campus",
                value: selectedCampus,
                displayName: CAMPUS_LABELS[selectedCampus] || selectedCampus,
              })
            }
            className="inline-flex items-center gap-1.5 rounded-xl bg-white/70 backdrop-blur-md border border-gray-200 shadow-sm px-3 py-2 text-xs font-medium text-gray-700 hover:bg-white/80 transition-colors"
          >
            <Pin className="w-3.5 h-3.5 text-blue-500" />
            Pin selected campus
          </button>
        </div>
      </header>

      <div className="h-full flex flex-col items-center px-4 pb-4 pt-28 min-h-0 overflow-hidden">
        {pinnedContext && (
          <div className="w-full max-w-2xl mb-3">
            <div className="inline-flex items-center gap-2 rounded-full bg-white/80 border border-gray-200 shadow-sm px-4 py-2 text-xs text-gray-700">
              <Pin className="w-3.5 h-3.5 text-blue-500" />
              <span>
                Pinned {pinnedContext.type}: {pinnedContext.displayName || pinnedContext.value}
              </span>
              <button
                onClick={() => setPinnedContext(null)}
                className="inline-flex items-center justify-center rounded-full hover:bg-gray-100 p-0.5 transition-colors"
                aria-label="Remove pinned context"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
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
                className="h-full overflow-y-auto styled-scrollbar space-y-4 py-4 scroll-smooth"
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
                      className={`max-w-[80%] px-4 py-3 rounded-2xl text-sm leading-relaxed break-words ${
                        msg.isUser
                          ? "bg-blue-50 text-gray-900 rounded-br-sm"
                          : "bg-white text-gray-900 shadow-sm border border-gray-100 rounded-bl-sm"
                      }`}
                    >
                      {msg.isUser ? msg.content : renderMarkdown(msg.content, msg.sources)}
                    </div>
                  </div>
                  {!msg.isUser && msg.confidence != null && (
                    <div className="ml-9 mt-1 flex items-center gap-1.5">
                      <div
                        className={`w-1.5 h-1.5 rounded-full ${
                          msg.confidence >= 0.7
                            ? "bg-green-500"
                            : msg.confidence >= 0.4
                            ? "bg-yellow-500"
                            : "bg-red-400"
                        }`}
                      />
                      <span className="text-[10px] text-gray-400">
                        {Math.round(msg.confidence * 100)}% confidence
                      </span>
                    </div>
                  )}
                  {!msg.isUser && msg.queryMetadata && (
                    <details className="mt-1 px-2 group ml-9 max-w-[80%] rounded-xl border border-gray-200 bg-white/70">
                      <summary className="cursor-pointer list-none px-3 py-2 text-[11px] text-gray-600 hover:text-gray-800 select-none inline-flex items-center gap-1.5 w-full">
                        <span className="inline-block transition-transform group-open:rotate-90">▶</span>
                        <Info className="w-3.5 h-3.5 text-blue-500" />
                        Query details
                      </summary>
                      <div className="px-3 pb-3 space-y-3 text-xs text-gray-600">
                        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                          {msg.queryMetadata.domain && (
                            <div className="rounded-lg bg-gray-50 px-2.5 py-2">
                              <div className="text-[10px] uppercase tracking-wide text-gray-400">Domain</div>
                              <div className="font-medium text-gray-700">{msg.queryMetadata.domain}</div>
                            </div>
                          )}
                          {msg.queryMetadata.task && (
                            <div className="rounded-lg bg-gray-50 px-2.5 py-2">
                              <div className="text-[10px] uppercase tracking-wide text-gray-400">Task</div>
                              <div className="font-medium text-gray-700">{msg.queryMetadata.task}</div>
                            </div>
                          )}
                          {msg.queryMetadata.routing_target && (
                            <div className="rounded-lg bg-gray-50 px-2.5 py-2">
                              <div className="text-[10px] uppercase tracking-wide text-gray-400">Route</div>
                              <div className="font-medium text-gray-700">{msg.queryMetadata.routing_target}</div>
                            </div>
                          )}
                          {msg.queryMetadata.confidence != null && (
                            <div className="rounded-lg bg-gray-50 px-2.5 py-2">
                              <div className="text-[10px] uppercase tracking-wide text-gray-400">Router confidence</div>
                              <div className="font-medium text-gray-700">
                                {Math.round(msg.queryMetadata.confidence * 100)}%
                              </div>
                            </div>
                          )}
                        </div>

                        {msg.queryMetadata.entities &&
                          Object.entries(msg.queryMetadata.entities).length > 0 && (
                            <div className="space-y-2">
                              <div className="text-[10px] uppercase tracking-wide text-gray-400">Matched entities</div>
                              <div className="flex flex-wrap gap-2">
                                {Object.entries(msg.queryMetadata.entities).map(([key, value]) => (
                                  <span
                                    key={`${msg.id}-entity-${key}`}
                                    className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-700"
                                  >
                                    {key}: {formatMetadataValue(value)}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}

                        {(msg.queryMetadata.decomposed || msg.queryMetadata.used_pinned_context) && (
                          <div className="flex flex-wrap gap-2">
                            {msg.queryMetadata.decomposed && (
                              <span className="inline-flex items-center rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-700">
                                Decomposed query
                              </span>
                            )}
                            {msg.queryMetadata.used_pinned_context && (
                              <span className="inline-flex items-center rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700">
                                Used pinned context
                              </span>
                            )}
                          </div>
                        )}

                        {msg.queryMetadata.freshness && (
                          <div className="rounded-lg bg-gray-50 px-2.5 py-2">
                            <div className="text-[10px] uppercase tracking-wide text-gray-400">Freshness</div>
                            <div className="font-medium text-gray-700">{msg.queryMetadata.freshness}</div>
                          </div>
                        )}

                        <div className="flex flex-wrap gap-2">
                          {(() => {
                            const campusContext = buildPinnedContextFromEntity(
                              "campus",
                              msg.queryMetadata.entities?.campus,
                            );
                            return campusContext ? (
                              <button
                                type="button"
                                onClick={() => handlePinContext(campusContext)}
                                className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-[11px] font-medium text-gray-700 hover:bg-gray-50"
                              >
                                <Pin className="w-3 h-3 text-blue-500" />
                                Pin campus
                              </button>
                            ) : null;
                          })()}
                          {(() => {
                            const programContext = buildPinnedContextFromEntity(
                              "program",
                              msg.queryMetadata.entities?.program,
                            );
                            return programContext ? (
                              <button
                                type="button"
                                onClick={() => handlePinContext(programContext)}
                                className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-[11px] font-medium text-gray-700 hover:bg-gray-50"
                              >
                                <Pin className="w-3 h-3 text-blue-500" />
                                Pin program
                              </button>
                            ) : null;
                          })()}
                          {(() => {
                            const departmentContext = buildPinnedContextFromEntity(
                              "department",
                              msg.queryMetadata.entities?.department,
                            );
                            return departmentContext ? (
                              <button
                                type="button"
                                onClick={() => handlePinContext(departmentContext)}
                                className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-[11px] font-medium text-gray-700 hover:bg-gray-50"
                              >
                                <Pin className="w-3 h-3 text-blue-500" />
                                Pin department
                              </button>
                            ) : null;
                          })()}
                        </div>
                      </div>
                    </details>
                  )}
                  {!msg.isUser && msg.sources && msg.sources.length > 0 && (
                    <details className="mt-1 px-2 group ml-9 max-w-[80%]">
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
