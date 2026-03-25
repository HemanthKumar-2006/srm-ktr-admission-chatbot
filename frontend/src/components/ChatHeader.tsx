import { Bot, Sparkles } from "lucide-react";

const ChatHeader = () => {
  return (
    <div className="flex items-center gap-3 p-4 border-b border-glass-border/30">
      <div className="relative">
        <div className="w-10 h-10 rounded-xl gradient-primary flex items-center justify-center glow-sm">
          <Bot className="w-5 h-5 text-primary-foreground" />
        </div>
        <div className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-emerald-400 border-2 border-card" />
      </div>
      <div className="flex-1">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-1.5">
          SRM KTR Admission Assistant
          <Sparkles className="w-3.5 h-3.5 text-primary" />
        </h3>
        <p className="text-xs text-muted-foreground">Ask about admissions, fees & courses</p>
      </div>
      <div className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-muted-foreground/40 hover:bg-primary transition-colors cursor-pointer"
          />
        ))}
      </div>
    </div>
  );
};

export default ChatHeader;
