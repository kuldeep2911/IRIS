// Mic button — toggles voice capture. The real-time loop runs server-side
// (iris/voice/wake.py); here it's a UI affordance + listening indicator.
import { useState } from "react";

export default function MicButton({ onText }: { onText?: (text: string) => void }) {
  const [listening, setListening] = useState(false);

  const toggle = () => {
    // Browser SpeechRecognition is used opportunistically if available.
    const SR =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) {
      setListening((l) => !l);
      return;
    }
    if (listening) {
      setListening(false);
      return;
    }
    const rec = new SR();
    rec.lang = "en-IN";
    rec.onresult = (e: any) => onText?.(e.results[0][0].transcript);
    rec.onend = () => setListening(false);
    rec.start();
    setListening(true);
  };

  return (
    <button
      onClick={toggle}
      title="Voice input"
      className={`grid h-10 w-10 place-items-center rounded-full transition ${
        listening ? "bg-red-500 animate-pulse" : "bg-white/10 hover:bg-white/20"
      }`}
    >
      🎙
    </button>
  );
}
