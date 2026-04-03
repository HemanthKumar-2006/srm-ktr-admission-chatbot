import { useState } from "react";
import { Send, Smile } from "lucide-react";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
}

const ChatInput = ({ onSend, disabled }: ChatInputProps) => {
  const [message, setMessage] = useState("");
  const [showEmojis, setShowEmojis] = useState(false);

  const emojis = ["😊", "👍", "🎉", "❤️", "🚀", "✨", "🤖", "💡"];

  const handleSend = () => {
    if (message.trim() && !disabled) {
      onSend(message.trim());
      setMessage("");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="p-3 border-t border-glass-border/30">
      {showEmojis && (
        <div className="flex gap-1 pb-2 animate-fade-in flex-wrap">
          {emojis.map((emoji) => (
            <button
              key={emoji}
              onClick={() => {
                setMessage((m) => m + emoji);
                setShowEmojis(false);
              }}
              className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-muted transition-colors text-base"
            >
              {emoji}
            </button>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setShowEmojis(!showEmojis)}
          className="w-9 h-9 flex items-center justify-center rounded-xl text-muted-foreground hover:text-foreground hover:bg-muted transition-all flex-shrink-0"
        >
          <Smile className="w-5 h-5" />
        </button>
        <input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a message..."
          disabled={disabled}
          className="flex-1 bg-muted rounded-xl px-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:ring-2 focus:ring-primary/30 transition-all"
        />
        <button
          onClick={handleSend}
          disabled={!message.trim() || disabled}
          className="w-9 h-9 flex items-center justify-center rounded-xl gradient-primary text-primary-foreground disabled:opacity-30 hover:opacity-90 transition-all flex-shrink-0 glow-sm disabled:shadow-none"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};

export default ChatInput;
