const TRANSLATIONS = {
  es: {
    "nav.how":              "Cómo funciona",
    "nav.plans":            "Planes",
    "hero.title.serif":     "Tu CV merece",
    "hero.title.sans":      "llegar a la entrevista.",
    "hero.action":          "Analizamos por qué no está pasando los filtros — y lo arreglamos.",
    "hero.badge":           "El 75% de los CVs son filtrados antes de llegar a un humano",
    "hero.stat.cvs":        "CVs optimizados",
    "hero.stat.users":      "profesionales",
    "hero.stat.templates":  "templates descargables",
    "point.1.title":        "Adaptamos tu CV a cada oferta",
    "point.1.desc":         "Integramos las keywords exactas que busca el ATS de esa empresa específica",
    "point.2.title":        "Superamos los filtros automáticos",
    "point.2.desc":         "El 75% de los CVs son rechazados por software antes de llegar a un humano",
    "point.3.title":        "Evaluamos la calidad real de tu CV",
    "point.3.desc":         "Composición, estructura, redacción de logros y diferenciación frente a otros candidatos",
    "form.title":           "Analizar mi CV",
    "form.job.placeholder": "Pega el texto de la oferta, o pega la URL del aviso laboral (LinkedIn, Trabajando, etc.)",
    "form.submit":          "Analizar compatibilidad ATS →",
  },
  en: {
    "nav.how":              "How it works",
    "nav.plans":            "Plans",
    "hero.title.serif":     "Your resume deserves",
    "hero.title.sans":      "to reach the interview.",
    "hero.action":          "We analyze why it's not passing the filters — and we fix it.",
    "hero.badge":           "75% of resumes are filtered out before a human sees them",
    "hero.stat.cvs":        "CVs optimized",
    "hero.stat.users":      "professionals",
    "hero.stat.templates":  "downloadable templates",
    "point.1.title":        "We adapt your CV to each job offer",
    "point.1.desc":         "We integrate the exact keywords the company's ATS is looking for",
    "point.2.title":        "We bypass automatic filters",
    "point.2.desc":         "75% of resumes are rejected by software before reaching a human",
    "point.3.title":        "We evaluate your CV's real quality",
    "point.3.desc":         "Composition, structure, achievement writing and differentiation from other candidates",
    "form.title":           "Analyze my CV",
    "form.job.placeholder": "Paste the job description, or the URL (LinkedIn, Indeed, etc.)",
    "form.submit":          "Analyze ATS compatibility →",
  },
  pt: {
    "nav.how":              "Como funciona",
    "nav.plans":            "Planos",
    "hero.title.serif":     "Seu currículo merece",
    "hero.title.sans":      "chegar à entrevista.",
    "hero.action":          "Analisamos por que não está passando nos filtros — e corrigimos.",
    "hero.badge":           "75% dos currículos são filtrados antes de chegar a um humano",
    "hero.stat.cvs":        "CVs otimizados",
    "hero.stat.users":      "profissionais",
    "hero.stat.templates":  "templates baixáveis",
    "point.1.title":        "Adaptamos seu CV para cada vaga",
    "point.1.desc":         "Integramos as keywords exatas que o ATS dessa empresa está buscando",
    "point.2.title":        "Superamos os filtros automáticos",
    "point.2.desc":         "75% dos currículos são rejeitados por software antes de chegar a um humano",
    "point.3.title":        "Avaliamos a qualidade real do seu CV",
    "point.3.desc":         "Composição, estrutura, redação de conquistas e diferenciação frente a outros candidatos",
    "form.title":           "Analisar meu CV",
    "form.job.placeholder": "Cole o texto da vaga, ou a URL (LinkedIn, etc.)",
    "form.submit":          "Analisar compatibilidade ATS →",
  }
};

function detectLang() {
  const urlLang = new URLSearchParams(window.location.search).get('lang');
  if (urlLang && TRANSLATIONS[urlLang]) return urlLang;

  const cookieLang = document.cookie.split(';')
    .find(c => c.trim().startsWith('ui_lang='))
    ?.split('=')[1]?.trim();
  if (cookieLang && TRANSLATIONS[cookieLang]) return cookieLang;

  const browserLang = (navigator.language || 'es').toLowerCase().substring(0, 2);
  if (browserLang === 'en') return 'en';
  if (browserLang === 'pt') return 'pt';
  return 'es';
}

function applyTranslations(lang) {
  const t = TRANSLATIONS[lang];
  if (!t) return;

  document.cookie = `ui_lang=${lang};path=/;max-age=${86400 * 30};samesite=lax`;

  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (t[key] !== undefined) el.textContent = t[key];
  });

  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    if (t[key] !== undefined) el.placeholder = t[key];
  });

  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-lang') === lang);
  });
}

window.setLang = function(lang) {
  applyTranslations(lang);
};

document.addEventListener('DOMContentLoaded', () => {
  applyTranslations(detectLang());
});
