import { Bot } from "lucide-react";

interface Source {
  index: number;
  title: string;
  url: string;
}

interface ChatMessageProps {
  content: string;
  isUser: boolean;
  timestamp: string;
  sources?: Source[];
  animationDelay?: number;
}

const ChatMessage = ({ content, isUser, timestamp, sources, animationDelay = 0 }: ChatMessageProps) => {
  return (
    <div
      className={`flex gap-2.5 ${isUser ? "flex-row-reverse" : "flex-row"} opacity-0 animate-fade-slide-up`}
      style={{ animationDelay: `${animationDelay}ms`, animationFillMode: "forwards" }}
    >
      {!isUser && (
        <div className="w-7 h-7 rounded-lg gradient-primary flex items-center justify-center flex-shrink-0 mt-1">
          <Bot className="w-3.5 h-3.5 text-primary-foreground" />
        </div>
      )}
      <div className={`max-w-[75%] flex flex-col ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
            isUser
              ? "gradient-primary text-primary-foreground rounded-br-md"
              : "bg-chat-bot text-chat-bot-foreground rounded-bl-md"
          }`}
        >
          {content}
        </div>
        {sources && sources.length > 0 && (
          <div className="mt-1.5 px-1 flex flex-col gap-0.5">
            {sources.map((src) => (
              <a
                key={src.index}
                href={src.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[10px] text-primary hover:underline truncate max-w-[240px]"
              >
                [{src.index}] {src.title !== src.url ? src.title : new URL(src.url).hostname}
              </a>
            ))}
          </div>
        )}
        <span className="text-[10px] text-muted-foreground mt-1 px-1">{timestamp}</span>
      </div>
    </div>
  );
};

export default ChatMessage;
