import { useState, useRef, useEffect } from "react";
import ChatHeader from "./ChatHeader";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import TypingIndicator from "./TypingIndicator";

interface Source {
  index: number;
  title: string;
  url: string;
}

interface Message {
  id: number;
  content: string;
  isUser: boolean;
  timestamp: string;
  sources?: Source[];
}

const API_URL = "/api/chat";

const getTime = () =>
  new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

const ChatWindow = () => {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 1,
      content: "Hello! I'm the SRM KTR Admission Assistant. Ask me anything about admissions, fees, courses, or campus life!",
      isUser: false,
      timestamp: getTime(),
    },
  ]);
  const [isTyping, setIsTyping] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isTyping]);

  const handleSend = async (content: string) => {
    const userMsg: Message = {
      id: Date.now(),
      content,
      isUser: true,
      timestamp: getTime(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsTyping(true);

    try {
      const res = await fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: content }),
      });

      if (!res.ok) {
        throw new Error(`Server error: ${res.status}`);
      }

      const data = await res.json();
      const botMsg: Message = {
        id: Date.now() + 1,
        content: data.response,
        isUser: false,
        timestamp: getTime(),
        sources: data.sources?.length ? data.sources : undefined,
      };
      setMessages((prev) => [...prev, botMsg]);
    } catch (err) {
      const errorMsg: Message = {
        id: Date.now() + 1,
        content: "Sorry, I couldn't connect to the server. Please make sure the backend is running.",
        isUser: false,
        timestamp: getTime(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <div className="glass-strong rounded-2xl overflow-hidden glow-primary flex flex-col w-full max-w-md h-[540px] float-animation">
      <ChatHeader />
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4 scroll-smooth">
        {messages.map((msg, i) => (
          <ChatMessage
            key={msg.id}
            content={msg.content}
            isUser={msg.isUser}
            timestamp={msg.timestamp}
            sources={msg.sources}
            animationDelay={i * 100}
          />
        ))}
        {isTyping && <TypingIndicator />}
      </div>
      <ChatInput onSend={handleSend} disabled={isTyping} />
    </div>
  );
};

export default ChatWindow;
