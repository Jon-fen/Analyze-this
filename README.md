# 🎯 CV Optimizer ATS

Optimiza tu CV para cualquier oferta laboral y supera los filtros automáticos ATS, usando Claude AI.

## Funcionalidades

- **Sube tu CV** en PDF o DOCX (o pega el texto directamente)
- **Pega la oferta laboral** a la que postulas
- **Claude analiza y adapta** tu CV con las keywords exactas del puesto
- **Score de compatibilidad ATS** con la oferta
- **Descarga en 2 templates** — Clásico o Moderno — listos para enviar

---

## Deploy en Streamlit Cloud (gratis, 5 minutos)

### 1. Sube el código a GitHub

```bash
git init
git add .
git commit -m "CV Optimizer ATS"
gh repo create cv-optimizer-ats --public --push --source=.
```

> Si no tienes `gh` instalado: crea el repo en github.com y sube los archivos manualmente.

### 2. Deploy en Streamlit Cloud

1. Ve a [share.streamlit.io](https://share.streamlit.io) e inicia sesión con GitHub
2. Clic en **"New app"**
3. Selecciona tu repositorio `cv-optimizer-ats`
4. **Main file path:** `app.py`
5. Clic en **"Deploy"** — listo en ~60 segundos

> ✅ No necesitas configurar variables de entorno. El usuario ingresa su propia API Key en la app.

---

## Uso local (opcional)

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## Stack

- **Frontend/Backend:** Streamlit (Python)
- **IA:** Claude claude-opus-4-5 via Anthropic API
- **PDF:** pdfplumber
- **Documentos:** python-docx
- **Deploy:** Streamlit Community Cloud (gratis)

---

## Próximas funciones (Fase 2)

- [ ] Sistema de usuarios con Supabase
- [ ] Créditos por usuario (free/premium)
- [ ] Más templates de CV
- [ ] Análisis por ATS específico (Workday, Lever, etc.)
- [ ] Exportación a PDF
