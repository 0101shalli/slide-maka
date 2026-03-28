import React, { useMemo, useState } from "react";
import { PreviewCard } from "./components/PreviewCard";

const palettes = [
  { id: 1, name: "Ocean", primary: "#0B3C5D" },
  { id: 2, name: "Forest", primary: "#2F5233" },
  { id: 3, name: "Sunset", primary: "#C44536" },
];

export function App() {
  const [slideCount, setSlideCount] = useState(10);
  const [theoryPercent, setTheoryPercent] = useState(70);
  const [imagePercent, setImagePercent] = useState(30);
  const [audienceLevel, setAudienceLevel] = useState("Beginner");
  const [paletteId, setPaletteId] = useState(1);
  const [text, setText] = useState("");
  const [status, setStatus] = useState("Idle");

  const wordCount = useMemo(() => text.trim().split(/\s+/).filter(Boolean).length, [text]);
  const practicalPercent = 100 - theoryPercent;

  async function generate() {
    setStatus("Structuring content...");
    const payload = {
      user_id: 1,
      original_text: text,
      configuration: {
        slide_count: slideCount,
        image_percent: imagePercent,
        theory_percent: theoryPercent,
        audience_level: audienceLevel,
        palette_id: Number(paletteId),
      },
    };

    const response = await fetch("http://localhost:8000/api/presentations/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      setStatus("Failed");
      return;
    }
    setStatus("Completed");
  }

  return (
    <main>
      <h1>SlideMaka Generator</h1>

      <section className="grid">
        <div className="card">
          <h3>Configuration Dashboard</h3>
          <label>
            Slide Count: {slideCount}
            <input type="range" min="5" max="50" value={slideCount} onChange={(e) => setSlideCount(Number(e.target.value))} />
          </label>

          <label>
            Theory %: {theoryPercent}
            <input type="range" min="0" max="100" value={theoryPercent} onChange={(e) => setTheoryPercent(Number(e.target.value))} />
          </label>
          <p>Practical %: {practicalPercent}</p>

          <label>
            Image Density %: {imagePercent}
            <input type="range" min="0" max="100" value={imagePercent} onChange={(e) => setImagePercent(Number(e.target.value))} />
          </label>

          <label>
            Audience Level
            <select value={audienceLevel} onChange={(e) => setAudienceLevel(e.target.value)}>
              <option>Beginner</option>
              <option>Intermediate</option>
              <option>Expert</option>
            </select>
          </label>

          <label>
            Palette
            <select value={paletteId} onChange={(e) => setPaletteId(e.target.value)}>
              {palettes.map((palette) => (
                <option value={palette.id} key={palette.id}>{palette.name}</option>
              ))}
            </select>
          </label>
        </div>

        <PreviewCard
          slideCount={slideCount}
          theoryPercent={theoryPercent}
          imagePercent={imagePercent}
          wordCount={wordCount}
        />
      </section>

      <section className="card">
        <h3>Text Input</h3>
        <textarea
          rows="10"
          placeholder="Paste your source text here"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <p>Words: {wordCount}</p>
      </section>

      <section className="card">
        <h3>Output & Download</h3>
        <button onClick={generate}>Generate PPTX/PDF</button>
        <p>Status: {status}</p>
      </section>
    </main>
  );
}
