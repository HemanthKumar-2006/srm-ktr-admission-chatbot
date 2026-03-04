import { useState, useRef, useEffect } from "react";
import ChatHeader from "./ChatHeader";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import TypingIndicator from "./TypingIndicator";

interface Message {
  id: number;
  content: string;
  isUser: boolean;
  timestamp: string;
}

const botResponses = [
  "That's a great question! Let me think about that for a moment. 🤔",
  "I'd be happy to help you with that! Here's what I think... ✨",
  "Interesting perspective! Based on my analysis, I'd suggest exploring that further. 🚀",
  "Absolutely! I can definitely assist with that. Let me break it down for you. 💡",
  "Great idea! Here are some suggestions that might help you get started. 🎯",
];

const getTime = () =>
  new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

const ChatWindow = () => {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 1,
      content: "Hey there! 👋 I'm Nova, your AI assistant. How can I help you today?",
      isUser: false,
      timestamp: getTime(),
    },
    {
      id: 2,
      content: "Hi Nova! I'd love to learn more about what you can do.",
      isUser: true,
      timestamp: getTime(),
    },
    {
      id: 3,
      content:
        "I can help with coding, creative writing, analysis, brainstorming, and so much more! Just ask me anything. ✨",
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

  const handleSend = (content: string) => {
    const userMsg: Message = {
      id: Date.now(),
      content,
      isUser: true,
      timestamp: getTime(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsTyping(true);

    setTimeout(() => {
      setIsTyping(false);
      const botMsg: Message = {
        id: Date.now() + 1,
        content: botResponses[Math.floor(Math.random() * botResponses.length)],
        isUser: false,
        timestamp: getTime(),
      };
      setMessages((prev) => [...prev, botMsg]);
    }, 1500 + Math.random() * 1000);
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
