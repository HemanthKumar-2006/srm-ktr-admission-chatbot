import { Sparkles, Zap, Shield } from "lucide-react";

const features = [
  { icon: Zap, label: "Lightning Fast" },
  { icon: Shield, label: "Secure & Private" },
  { icon: Sparkles, label: "AI-Powered" },
];

const HeroSection = () => {
  return (
    <div className="flex flex-col justify-center space-y-8 max-w-lg">
      <div className="space-y-4 opacity-0 animate-fade-slide-up" style={{ animationFillMode: "forwards" }}>
        <div className="inline-flex items-center gap-2 glass rounded-full px-4 py-1.5 text-xs font-medium text-muted-foreground">
          <Sparkles className="w-3.5 h-3.5 text-primary" />
          Next-gen AI Assistant
        </div>
        <h1 className="text-5xl lg:text-6xl font-extrabold tracking-tight leading-[1.1]">
          <span className="text-foreground">Meet </span>
          <span className="gradient-text">Nova</span>
          <span className="text-foreground">.</span>
        </h1>
        <p className="text-lg text-muted-foreground leading-relaxed max-w-sm">
          Your intelligent companion for conversations that matter. Powered by cutting-edge AI.
        </p>
      </div>

      <div
        className="flex flex-wrap gap-3 opacity-0 animate-fade-slide-up"
        style={{ animationDelay: "200ms", animationFillMode: "forwards" }}
      >
        {features.map(({ icon: Icon, label }) => (
          <div
            key={label}
            className="glass rounded-xl px-4 py-2.5 flex items-center gap-2 text-sm text-secondary-foreground hover:bg-muted/60 transition-all cursor-default"
          >
            <Icon className="w-4 h-4 text-primary" />
            {label}
          </div>
        ))}
      </div>

      <div
        className="flex items-center gap-4 opacity-0 animate-fade-slide-up"
        style={{ animationDelay: "400ms", animationFillMode: "forwards" }}
      >
        <div className="flex -space-x-2">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="w-8 h-8 rounded-full border-2 border-background gradient-primary"
              style={{ opacity: 1 - i * 0.15 }}
            />
          ))}
        </div>
        <p className="text-sm text-muted-foreground">
          <span className="text-foreground font-semibold">2.4k+</span> active users
        </p>
      </div>
    </div>
  );
};

export default HeroSection;
