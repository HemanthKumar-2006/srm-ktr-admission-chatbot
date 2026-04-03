const FloatingOrbs = () => {
  return (
    <div className="fixed inset-0 pointer-events-none overflow-hidden" aria-hidden="true">
      <div
        className="absolute w-[500px] h-[500px] rounded-full opacity-[0.07] blur-[120px] animate-pulse-glow"
        style={{
          background: "hsl(262 80% 60%)",
          top: "10%",
          left: "20%",
        }}
      />
      <div
        className="absolute w-[400px] h-[400px] rounded-full opacity-[0.05] blur-[100px] animate-pulse-glow"
        style={{
          background: "hsl(280 70% 55%)",
          bottom: "20%",
          right: "10%",
          animationDelay: "1.5s",
        }}
      />
      <div
        className="absolute w-[300px] h-[300px] rounded-full opacity-[0.04] blur-[80px] animate-pulse-glow"
        style={{
          background: "hsl(240 70% 55%)",
          top: "50%",
          left: "60%",
          animationDelay: "3s",
        }}
      />
    </div>
  );
};

export default FloatingOrbs;
