import { Bot } from "lucide-react";

const TypingIndicator = () => {
  return (
    <div className="flex gap-2.5 animate-fade-in">
      <div className="w-7 h-7 rounded-lg gradient-primary flex items-center justify-center flex-shrink-0 mt-1">
        <Bot className="w-3.5 h-3.5 text-primary-foreground" />
      </div>
      <div className="bg-chat-bot rounded-2xl rounded-bl-md px-4 py-3 flex items-center gap-1.5">
        <div className="w-2 h-2 rounded-full bg-muted-foreground typing-dot" />
        <div className="w-2 h-2 rounded-full bg-muted-foreground typing-dot" />
        <div className="w-2 h-2 rounded-full bg-muted-foreground typing-dot" />
      </div>
    </div>
  );
};

export default TypingIndicator;
