"""Shared dependencies — imported by all routers to avoid re-instantiating."""
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")
