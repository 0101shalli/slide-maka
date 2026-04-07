import React from "react";

export function PreviewCard({ slideCount, theoryPercent, imagePercent, wordCount }) {
  const theorySlides = Math.round(slideCount * (theoryPercent / 100));
  const practicalSlides = slideCount - theorySlides;
  const imageSlides = Math.round(slideCount * (imagePercent / 100));
  const minimumWords = slideCount * 18;

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
