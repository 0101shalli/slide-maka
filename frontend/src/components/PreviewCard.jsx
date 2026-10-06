import React from "react";

// Keep in step with backend/app/services/parameter_calculator.py: the deck
// spends four slides on cover, outline, recap and thank-you, so the theory /
// practical / image counts apply to the remaining content slides only.
const STRUCTURAL_SLIDES = 4;
const MIN_WORDS_PER_SLIDE = 18;

export function PreviewCard({ slideCount, theoryPercent, imagePercent, wordCount }) {
  const contentSlides = Math.max(slideCount - STRUCTURAL_SLIDES, 1);
  const theorySlides = Math.round(contentSlides * (theoryPercent / 100));
  const practicalSlides = contentSlides - theorySlides;
  const imageSlides = Math.min(contentSlides, Math.round(contentSlides * (imagePercent / 100)));
  const minimumWords = contentSlides * MIN_WORDS_PER_SLIDE;

  return (
    <div className="card">
      <h3>Preview Calculator</h3>
      <p>Total Slides: {slideCount}</p>
      <p>Theory Slides: {theorySlides}</p>
      <p>Practical Slides: {practicalSlides}</p>
      <p>Slides with Images: {imageSlides}</p>
      <p className={wordCount < minimumWords ? "warn" : "ok"}>
        Word Count: {wordCount} (recommended {minimumWords}+)
      </p>
    </div>
  );
}
