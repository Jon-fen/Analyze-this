// Analyze-This FastAPI — app.js

// ─── Score ring animation fix ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const ring = document.querySelector('.score-ring');
  if (ring) {
    const dash = ring.style.getPropertyValue('--dash') || ring.getAttribute('stroke-dasharray')?.split(' ')[0];
    const circ = 339;
    if (dash) {
      ring.style.strokeDasharray = `0 ${circ}`;
      requestAnimationFrame(() => {
        ring.style.transition = 'stroke-dasharray 1.2s cubic-bezier(0.34, 1.56, 0.64, 1)';
        ring.style.strokeDasharray = `${dash} ${circ}`;
      });
    }
  }

  // Animate breakdown bars
  document.querySelectorAll('.breakdown-bar-fill').forEach(bar => {
    const targetWidth = bar.style.width;
    bar.style.width = '0';
    requestAnimationFrame(() => {
      bar.style.transition = 'width 0.9s ease-out';
      bar.style.width = targetWidth;
    });
  });
});
