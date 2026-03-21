"""
Shared Jinja2Templates instance.
All routers import `templates` from here so globals set at startup
(SUPABASE_URL, SUPABASE_KEY) are visible in every template.
"""
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")
