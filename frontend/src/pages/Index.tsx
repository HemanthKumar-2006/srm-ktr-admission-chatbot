import { useState, useRef, useEffect } from "react";
import { Send, Bot } from "lucide-react";
import FloatingOrbs from "@/components/FloatingOrbs";

interface Message {
  id: number;
  content: string;
  isUser: boolean;
}

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

  // 🚀 REAL BACKEND CALL
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
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query: userText }),
      });

      const data = await res.json();

      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          content: data.response || "No response from server.",
          isUser: false,
        },
      ]);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          content: "⚠️ Cannot connect to SRM server.",
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
            className="w-full max-h-[40vh] overflow-y-auto space-y-3 mb-6 px-1 scroll-smooth"
          >
            {messages.map((msg) => (
              <div key={msg.id} className={`flex ${msg.isUser ? "justify-end" : "justify-start"}`}>
                {!msg.isUser && (
                  <div className="w-7 h-7 rounded-lg gradient-primary flex items-center justify-center mr-2 mt-1">
                    <Bot className="w-3.5 h-3.5 text-primary-foreground" />
                  </div>
                )}
                <div
                  className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-sm ${
                    msg.isUser
                      ? "gradient-primary text-primary-foreground"
                      : "glass text-foreground"
                  }`}
                >
                  {msg.content}
                </div>
              </div>
            ))}

            {isTyping && (
              <div className="flex justify-start">
                <div className="w-7 h-7 rounded-lg gradient-primary flex items-center justify-center mr-2 mt-1">
                  <Bot className="w-3.5 h-3.5 text-primary-foreground" />
                </div>
                <div className="glass rounded-2xl px-4 py-3">Typing…</div>
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