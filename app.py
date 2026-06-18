"""Vates hírlevél-automatizáló — Flask varázsló (6 lépés)."""

import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import (
    Flask, abort, jsonify, redirect, render_template, request,
    send_from_directory, session, url_for,
)

load_dotenv()

import ai_client
import image_composer
import klaviyo_client

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-secret")

# Belépési védelem — a felhasználónév és jelszó env változóból jön (Railway),
# sosem a kódból. Ha az APP_PASSWORD nincs beállítva, az app zárva marad
# (biztonságos alapértelmezés).
APP_USERNAME = os.environ.get("APP_USERNAME", "Vates")
APP_PASSWORD = os.environ.get("APP_PASSWORD")
# auth nélkül elérhető végpontok (Railway health-check, statikus fájlok, belépés)
PUBLIC_ENDPOINTS = {"health", "login", "static"}

BUDAPEST = ZoneInfo("Europe/Budapest")
SESSION_DIR = os.path.join("tmp", "sessions")
ALLOWED_PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
SOURCE_PHOTO = "source_photo.jpg"

MOODS = [
    ("playful", "Játékos"), ("emotional", "Érzelmes"), ("urgent", "Sürgető"),
    ("informational", "Informatív"), ("nostalgic", "Nosztalgikus"), ("bold", "Merész"),
]

STEPS = [
    ("step1", "Szöveg generálása"),
    ("step2", "Szöveg és linkek"),
    ("step3", "Header kép"),
    ("step4", "Header finomhangolás"),
    ("step5", "Időzítés és célközönség"),
    ("step6", "Végső ellenőrzés"),
]


# ---------------------------------------------------------------------------
# Szerveroldali session állapot (a wizard adatai nem férnének a cookie-ba)
# ---------------------------------------------------------------------------

def _sid():
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return session["sid"]


def _state_path():
    return os.path.join(SESSION_DIR, f"{_sid()}.json")


def load_state():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(SESSION_DIR, exist_ok=True)
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def session_image_dir():
    path = os.path.join(SESSION_DIR, _sid())
    os.makedirs(path, exist_ok=True)
    return path


@app.context_processor
def inject_globals():
    return {"steps": STEPS, "moods": MOODS}


# ---------------------------------------------------------------------------
# Belépési védelem — minden oldal mögött, a publikus végpontok kivételével
# ---------------------------------------------------------------------------

@app.before_request
def require_login():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if session.get("authed"):
        return None
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if not APP_PASSWORD:
            error = ("A jelszavas védelem nincs beállítva — add meg az APP_PASSWORD "
                     "(és opcionálisan az APP_USERNAME) környezeti változót a Railwayen.")
        else:
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            # bájtokra kódolva, hogy az ékezetes jelszó is működjön
            ok = (hmac.compare_digest(username.encode("utf-8"), APP_USERNAME.encode("utf-8"))
                  and hmac.compare_digest(password.encode("utf-8"), APP_PASSWORD.encode("utf-8")))
            if ok:
                session["authed"] = True
                return redirect(url_for("index"))
            error = "Hibás felhasználónév vagy jelszó."
    return render_template("login.html", error=error, active=None)


@app.get("/logout")
def logout():
    session.pop("authed", None)
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Alap útvonalak
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/")
def index():
    return redirect(url_for("step1"))


@app.get("/tmp-image/<filename>")
def tmp_image(filename):
    if "/" in filename or "\\" in filename or filename.startswith("."):
        abort(404)
    return send_from_directory(os.path.abspath(session_image_dir()), filename)


# ---------------------------------------------------------------------------
# Stílusprofil (admin)
# ---------------------------------------------------------------------------

def get_style_profile():
    cache = ai_client.load_style_cache()
    return cache["profile"] if cache else None


@app.route("/admin/style", methods=["GET", "POST"])
def style_admin():
    """A stílusprofil felépítése copy-paste híddal.

    A program kinyeri a korábbi 50 kampányt a Klaviyo-ból, és összeállít egy
    promptot. Az operátor ezt a saját Claude-chatjébe másolja, a választ
    (a stílusprofilt) visszamásolja, és elmentjük.
    """
    error = None
    prompt = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "build_prompt":
            try:
                corpus = klaviyo_client.fetch_sent_campaign_corpus(limit=50)
                prompt = ai_client.build_style_analysis_prompt(corpus)
            except Exception as exc:  # noqa: BLE001
                error = f"Nem sikerült lekérni a korábbi kampányokat: {exc}"
        elif action == "save_profile":
            pasted = request.form.get("profile", "").strip()
            if not pasted:
                error = "Illeszd be a Claude által adott stílusprofilt."
            else:
                ai_client.save_style_profile(pasted)
                return redirect(url_for("step1"))
    return render_template(
        "style_admin.html", error=error, prompt=prompt,
        style_cache=ai_client.load_style_cache(), active=None,
    )


# ---------------------------------------------------------------------------
# 1. lépés: szöveggenerálás
# ---------------------------------------------------------------------------

@app.route("/step1", methods=["GET", "POST"])
def step1():
    state = load_state()
    error = None
    prompt = None
    if request.method == "POST":
        action = request.form.get("action")
        # a paraméterek minden POST-nál mentődnek, hogy ne vesszenek el
        state["topic"] = request.form.get("topic", state.get("topic", "")).strip()
        state["adherence"] = int(request.form.get("adherence", state.get("adherence", 80)))
        if "moods" in request.form:
            state["selected_moods"] = request.form.getlist("moods")
        state["notes"] = request.form.get("notes", state.get("notes", "")).strip()

        if action == "build_prompt":
            profile = get_style_profile()
            if not state["topic"]:
                error = "Add meg a kampány témáját!"
            elif not profile:
                error = "Először építsd fel a stílusprofilt (lenti link)."
            else:
                prompt = ai_client.build_text_generation_prompt(
                    state["topic"], state["adherence"],
                    state.get("selected_moods", []), state["notes"], profile,
                )
            save_state(state)
        elif action == "use_response":
            pasted = request.form.get("response", "").strip()
            if not pasted:
                error = "Illeszd be a Claude által adott JSON választ."
            else:
                try:
                    state.update(ai_client.parse_text_response(pasted))
                except Exception as exc:  # noqa: BLE001
                    error = f"A válasz nem értelmezhető: {exc}"
            save_state(state)
        elif action == "continue":
            state["subject"] = request.form.get("subject", "").strip()[:60]
            state["preview_text"] = request.form.get("preview_text", "").strip()[:90]
            state["body"] = request.form.get("body", "").strip()
            if not (state["subject"] and state["body"]):
                error = "A tárgy és a törzs nem lehet üres."
            else:
                save_state(state)
                return redirect(url_for("step2"))
    return render_template(
        "step1_text.html", state=state, error=error, active="step1",
        style_cache=ai_client.load_style_cache(), prompt=prompt,
    )


# ---------------------------------------------------------------------------
# 2. lépés: linkek
# ---------------------------------------------------------------------------

@app.route("/step2", methods=["GET", "POST"])
def step2():
    state = load_state()
    if not state.get("body"):
        return redirect(url_for("step1"))
    error = None

    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_manual":
            anchor = request.form.get("anchor", "").strip()
            url = request.form.get("url", "").strip()
            if not anchor or anchor not in state["body"]:
                error = "A horgonyszöveg karakterre pontosan szerepeljen a levél szövegében."
            elif not ai_client.is_vates_url(url):
                error = "Csak vates.hu domainre mutató link adható meg."
            else:
                state.setdefault("links", []).append(
                    {"anchor": anchor, "url": url, "highlight": False}
                )
        elif action == "remove":
            idx = int(request.form.get("index", -1))
            if 0 <= idx < len(state.get("links", [])):
                state["links"].pop(idx)
        elif action == "update":
            idx = int(request.form.get("index", -1))
            url = request.form.get("url", "").strip()
            if 0 <= idx < len(state.get("links", [])):
                if ai_client.is_vates_url(url):
                    state["links"][idx]["url"] = url
                    state["links"][idx]["highlight"] = bool(request.form.get("highlight"))
                else:
                    error = "Csak vates.hu domainre mutató link adható meg."
        elif action == "set_header":
            href = request.form.get("header_href", "").strip()
            if ai_client.is_vates_url(href):
                state["header_href"] = href
            else:
                error = "A header link csak vates.hu URL lehet."
        elif action == "continue":
            if not state.get("links"):
                error = "Legalább egy linket rendelj a szöveghez."
            else:
                save_state(state)
                return redirect(url_for("step3"))
        save_state(state)

    state.setdefault("links", [])
    state.setdefault("header_href", "https://vates.hu/")
    save_state(state)

    return render_template(
        "step2_links.html", state=state, error=error, active="step2",
        vates_urls=ai_client.load_vates_urls(),
    )


# ---------------------------------------------------------------------------
# 3. lépés: fotó feltöltése + headline-variánsok generálása
# ---------------------------------------------------------------------------

@app.route("/step3", methods=["GET", "POST"])
def step3():
    state = load_state()
    if not state.get("links"):
        return redirect(url_for("step2"))
    error = None

    if request.method == "POST":
        action = request.form.get("action")
        if action == "upload":
            file = request.files.get("photo")
            ext = os.path.splitext(file.filename or "")[1].lower() if file else ""
            if not file or not file.filename:
                error = "Válassz egy képfájlt."
            elif ext not in ALLOWED_PHOTO_EXT:
                error = "Csak JPG, PNG vagy WEBP kép tölthető fel."
            else:
                try:
                    from PIL import Image
                    img = Image.open(file.stream)
                    img = img.convert("RGB")
                    img.save(os.path.join(session_image_dir(), SOURCE_PHOTO),
                             "JPEG", quality=92)
                    state["source_photo"] = SOURCE_PHOTO
                    state.pop("header_variants", None)
                    state.pop("selected_variant", None)
                except Exception as exc:  # noqa: BLE001
                    error = f"A kép nem dolgozható fel: {exc}"
        elif action == "use_headlines":
            pasted = request.form.get("response", "").strip()
            picks = ai_client.parse_headline_response(pasted) if pasted else []
            if not picks:
                error = "Illeszd be a Claude által adott feliratokat (3 db)."
            else:
                photo_path = os.path.join(session_image_dir(), state["source_photo"])
                variants = []
                for i, pick in enumerate(picks, start=1):
                    out = os.path.join(session_image_dir(), f"header_v{i}.jpg")
                    used_size = image_composer.compose_header(
                        photo_path, pick["headline"], out, position=pick["position"],
                    )
                    variants.append({
                        "file": f"header_v{i}.jpg",
                        "photo": state["source_photo"],
                        "headline": pick["headline"],
                        "position": pick["position"],
                        "font_size": used_size,
                        "color": "#FFFFFF",
                        "reason": pick["reason"],
                    })
                state["header_variants"] = variants
                state.pop("selected_variant", None)
        elif action == "select":
            idx = int(request.form.get("variant", -1))
            if 0 <= idx < len(state.get("header_variants", [])):
                state["selected_variant"] = idx
                save_state(state)
                return redirect(url_for("step4"))
        elif action == "regenerate":
            state.pop("header_variants", None)
        elif action == "new_photo":
            state.pop("source_photo", None)
            state.pop("header_variants", None)
            state.pop("selected_variant", None)
        save_state(state)

    prompt = ai_client.build_headline_prompt(state["body"]) if state.get("source_photo") else None
    return render_template(
        "step3_image.html", state=state, error=error, active="step3",
        cache_bust=int(time.time()), din_ok=image_composer.din_font_available(),
        prompt=prompt,
    )


# ---------------------------------------------------------------------------
# 4. lépés: header finomhangolás
# ---------------------------------------------------------------------------

@app.route("/step4", methods=["GET", "POST"])
def step4():
    state = load_state()
    if state.get("selected_variant") is None:
        return redirect(url_for("step3"))
    variant = state["header_variants"][state["selected_variant"]]

    if request.method == "POST":  # nem-JS fallback: form POST újrakompozitál
        _apply_adjustments(state, variant, request.form)
        save_state(state)
        if request.form.get("action") == "finalize":
            return redirect(url_for("step5"))

    return render_template(
        "step4_adjust.html", state=state, variant=variant, active="step4",
        cache_bust=int(time.time()), positions=image_composer.POSITIONS,
    )


def _apply_adjustments(state, variant, form):
    variant["headline"] = form.get("headline", variant["headline"]).strip().upper()
    variant["position"] = form.get("position", variant["position"])
    variant["color"] = form.get("color", variant["color"])
    try:
        variant["font_size"] = int(form.get("font_size") or variant["font_size"] or 64)
    except ValueError:
        pass
    out = os.path.join(session_image_dir(), variant["file"])
    used = image_composer.compose_header(
        os.path.join(session_image_dir(), variant["photo"]), variant["headline"],
        out, position=variant["position"], font_size=variant["font_size"],
        color=variant["color"],
    )
    variant["font_size"] = used


@app.post("/recomposite")
def recomposite():
    state = load_state()
    if state.get("selected_variant") is None:
        return jsonify({"error": "Nincs kiválasztott variáns."}), 400
    variant = state["header_variants"][state["selected_variant"]]
    _apply_adjustments(state, variant, request.json or {})
    save_state(state)
    return jsonify({
        "url": url_for("tmp_image", filename=variant["file"]) + f"?t={int(time.time())}",
        "font_size": variant["font_size"],
    })


# ---------------------------------------------------------------------------
# 5. lépés: időzítés és célközönség
# ---------------------------------------------------------------------------

@app.route("/step5", methods=["GET", "POST"])
def step5():
    state = load_state()
    if state.get("selected_variant") is None:
        return redirect(url_for("step3"))
    error = None

    if request.method == "POST":
        audiences = request.form.getlist("audiences")
        date_str = request.form.get("send_date", "")
        time_str = request.form.get("send_time", "")
        name = request.form.get("campaign_name", "").strip()
        if not audiences:
            error = "Legalább egy listát vagy szegmenst válassz ki."
        elif not (date_str and time_str):
            error = "Add meg a küldés dátumát és időpontját."
        else:
            try:
                local_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                local_dt = local_dt.replace(tzinfo=BUDAPEST)
            except ValueError:
                error = "Érvénytelen dátum vagy időpont."
                local_dt = None
            if local_dt and local_dt <= datetime.now(BUDAPEST):
                error = "A küldési időpont nem lehet a múltban."
            elif local_dt:
                state["audiences"] = audiences
                state["send_local"] = local_dt.strftime("%Y-%m-%d %H:%M")
                state["send_utc"] = (
                    local_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                )
                state["campaign_name"] = name or default_campaign_name(state)
                save_state(state)
                return redirect(url_for("step6"))

    try:
        lists = klaviyo_client.get_lists()
        segments = klaviyo_client.get_segments()
    except Exception as exc:  # noqa: BLE001
        lists, segments = [], []
        error = error or f"Nem sikerült lekérni a listákat: {exc}"

    return render_template(
        "step5_schedule.html", state=state, error=error, active="step5",
        lists=lists, segments=segments,
        default_name=state.get("campaign_name") or default_campaign_name(state),
        min_date=datetime.now(BUDAPEST).strftime("%Y-%m-%d"),
    )


def default_campaign_name(state):
    return f"[{datetime.now(BUDAPEST).strftime('%Y-%m-%d')}] {state.get('subject', '')}"


# ---------------------------------------------------------------------------
# 6. lépés: végső ellenőrzés és beküldés
# ---------------------------------------------------------------------------

@app.route("/step6", methods=["GET", "POST"])
def step6():
    state = load_state()
    if not state.get("send_utc"):
        return redirect(url_for("step5"))
    error = None

    if request.method == "POST":
        master_id = os.environ.get("KLAVIYO_TEMPLATE_ID", "")
        if not master_id:
            error = "Hiányzik a KLAVIYO_TEMPLATE_ID környezeti változó."
        else:
            variant = state["header_variants"][state["selected_variant"]]
            body_html = klaviyo_client.build_body_html(state["body"], state["links"])
            try:
                campaign_id = klaviyo_client.submit_full_campaign(
                    master_template_id=master_id,
                    header_image_path=os.path.join(session_image_dir(), variant["file"]),
                    header_alt=variant["headline"] or state["subject"],
                    header_href=state.get("header_href", "https://vates.hu/"),
                    body_html=body_html,
                    campaign_name=state["campaign_name"],
                    audience_ids=state["audiences"],
                    send_datetime_utc=state["send_utc"],
                    subject=state["subject"],
                    preview_text=state["preview_text"],
                )
                state["campaign_id"] = campaign_id
                save_state(state)
                return render_template(
                    "step6_review.html", state=state, active="step6",
                    success=True, campaign_id=campaign_id,
                    cache_bust=int(time.time()),
                )
            except Exception as exc:  # noqa: BLE001
                error = f"A beküldés nem sikerült (minden részleges erőforrás törölve): {exc}"

    variant = state["header_variants"][state["selected_variant"]]
    audience_names = []
    try:
        all_groups = {g["id"]: g["name"] for g in
                      klaviyo_client.get_lists() + klaviyo_client.get_segments()}
        audience_names = [all_groups.get(a, a) for a in state["audiences"]]
    except Exception:  # noqa: BLE001
        audience_names = state["audiences"]

    return render_template(
        "step6_review.html", state=state, error=error, active="step6",
        success=False, variant=variant, audience_names=audience_names,
        cache_bust=int(time.time()),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
