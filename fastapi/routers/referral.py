"""
Referral system: generate unique referral links, track signups, grant bonus credits.

NOTE: Requires a DB migration to add `referral_redeemed` boolean column to the
`profiles` table. Until the migration is run, the column will be missing and
`profile.get("referral_redeemed")` will return None (falsy), which means the
duplicate-redeem guard won't block — apply the migration before going to production:
    ALTER TABLE profiles ADD COLUMN referral_redeemed boolean NOT NULL DEFAULT false;
"""
import hashlib
from fastapi import APIRouter, Request, Form
from fastapi.responses import JSONResponse

from services.session import _sb_admin, _get_profile, RAILWAY_URL

router = APIRouter(prefix="/referral")


def _make_referral_code(user_id: str) -> str:
    """Deterministic 8-char code from user_id."""
    return hashlib.md5(user_id.encode()).hexdigest()[:8].upper()


@router.get("/my-link")
async def get_my_referral_link(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        return JSONResponse({"ok": False, "error": "login_required"})
    # Use stored referral_code if available, else fall back to deterministic
    code = user.get("referral_code") or _make_referral_code(user["id"])
    link = f"{RAILWAY_URL}/?ref={code}"
    return JSONResponse({"ok": True, "code": code, "link": link})


@router.post("/redeem")
async def redeem_referral(request: Request, ref_code: str = Form(...)):
    """
    Called after a new user registers with ?ref=CODE.
    Grant +2 bonus analyses to both the new user and the referrer.
    """
    user = getattr(request.state, "user", None)
    if not user:
        return JSONResponse({"ok": False, "error": "login_required"})

    try:
        sb = _sb_admin()
        # Find referrer by their deterministic code
        all_profiles = sb.table("profiles").select("id").execute()
        referrer_id = None
        for p in (all_profiles.data or []):
            if _make_referral_code(p["id"]) == ref_code.upper():
                referrer_id = p["id"]
                break

        if not referrer_id or referrer_id == user["id"]:
            return JSONResponse({"ok": False, "error": "Código de referido inválido."})

        # Check if this user already redeemed a referral (prevent double-dipping)
        profile = _get_profile(sb, user["id"])
        if profile.get("referral_redeemed"):
            return JSONResponse({"ok": False, "error": "Ya usaste un código de referido."})

        # Grant 2 bonus credits to new user
        cur_used = profile.get("credits_used_this_month", 0)
        new_used = max(0, cur_used - 2)  # effectively give 2 free credits
        sb.table("profiles").update({
            "credits_used_this_month": new_used,
            "referral_redeemed": True,
        }).eq("id", user["id"]).execute()

        # Grant 2 bonus credits to referrer
        ref_profile = _get_profile(sb, referrer_id)
        ref_used = ref_profile.get("credits_used_this_month", 0)
        sb.table("profiles").update({
            "credits_used_this_month": max(0, ref_used - 2),
        }).eq("id", referrer_id).execute()

        return JSONResponse({"ok": True, "msg": "¡+2 análisis para ti y tu referido!"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})
