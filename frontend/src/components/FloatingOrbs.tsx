const FloatingOrbs = () => {
  return (
    <div className="fixed inset-0 pointer-events-none overflow-hidden" aria-hidden="true">
      <div
        className="absolute w-[500px] h-[500px] rounded-full opacity-[0.15] blur-[120px] animate-pulse-glow mix-blend-multiply"
        style={{
          background: "hsl(250 80% 50%)",
          top: "10%",
          left: "20%",
        }}
      />
      <div
        className="absolute w-[400px] h-[400px] rounded-full opacity-[0.15] blur-[100px] animate-pulse-glow mix-blend-multiply"
        style={{
          background: "hsl(280 80% 50%)",
          bottom: "20%",
          right: "10%",
          animationDelay: "1.5s",
        }}
      />
      <div
        className="absolute w-[300px] h-[300px] rounded-full opacity-[0.12] blur-[80px] animate-pulse-glow mix-blend-multiply"
        style={{
          background: "hsl(220 80% 50%)",
          top: "50%",
          left: "60%",
          animationDelay: "3s",
        }}
      />
    </div>
  );
};

export default FloatingOrbs;
