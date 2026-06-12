"""Minden Claude API hívás: stíluselemzés, szöveggenerálás, linkajánlás,
fotóválasztás, headline-generálás, vizuális stílusprofil."""

import base64
import io
import json
import os
import re

import anthropic
from PIL import Image

MODEL = "claude-sonnet-4-20250514"
STYLE_CACHE_FILE = "style_cache.json"
VISUAL_CACHE_FILE = "visual_style_cache.json"
URLS_FILE = os.path.join("data", "vates_urls.json")

MOOD_LABELS = {
    "playful": "játékos",
    "emotional": "érzelmes",
    "urgent": "sürgető",
    "informational": "informatív",
    "nostalgic": "nosztalgikus",
    "bold": "merész",
}


def _client():
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _extract_json(text):
    """JSON kinyerése a modell válaszából (tűri a ```json blokkot is)."""
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1)
    start = text.find("{")
    if start == -1:
        start = text.find("[")
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start:end + 1])


def load_vates_urls():
    with open(URLS_FILE, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Stílusprofil a korábbi kampányokból
# ---------------------------------------------------------------------------

def load_style_cache():
    if os.path.exists(STYLE_CACHE_FILE):
        with open(STYLE_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def build_style_profile(corpus):
    """Claude elemzi a kampányszöveg-korpuszt, és stílusprofilt készít."""
    samples = []
    for item in corpus[:50]:
        samples.append(
            f"--- Kampány: {item['name']}\nTárgy: {item['subject']}\n"
            f"Előnézet: {item['preview_text']}\nTörzs:\n{item['body_text'][:2500]}"
        )
    prompt = (
        "Az alábbiakban a Vates (vates.hu) magyar ruhamárka korábban elküldött "
        "hírlevelei találhatók. Elemezd a korpuszt, és készíts részletes "
        "stílusprofilt, amit később hírlevélírásra használunk rendszerpromptként.\n\n"
        "A profil térjen ki:\n"
        "- tipikus mondathossz és ritmus\n"
        "- gyakori nyitóformulák (pl. \"Volt egy pillanat...\")\n"
        "- érzelmi horgok és storytelling-szerkezet\n"
        "- CTA-megfogalmazási konvenciók\n"
        "- félkövér kiemelések használata, tegeződés, emoji-gyakoriság és -elhelyezés\n"
        "- tárgymezők és előnézeti szövegek mintázatai\n\n"
        "Tömör, jól strukturált magyar nyelvű profilt írj.\n\n"
        + "\n\n".join(samples)
    )
    resp = _client().messages.create(
        model=MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    profile = resp.content[0].text
    with open(STYLE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"profile": profile, "corpus_size": len(corpus)}, f, ensure_ascii=False, indent=1)
    return profile


# ---------------------------------------------------------------------------
# Szöveggenerálás
# ---------------------------------------------------------------------------

def generate_email_text(topic, adherence, moods, notes, style_profile,
                        previous=None, feedback=None):
    """Tárgy + előnézet + törzs generálása magyarul. Visszatérés: dict."""
    if adherence >= 80:
        style_instruction = "Kövesd PONTOSAN a fenti Vates-stílusprofilt: szerkezet, ritmus, emoji-használat, CTA-stílus."
    elif adherence >= 50:
        style_instruction = "Nagyrészt kövesd a Vates-stílusprofilt, de kisebb kreatív eltérések megengedettek."
    elif adherence >= 20:
        style_instruction = "A stílusprofil csak laza iránymutatás — bátran írj saját hangon, de maradj hű a márka értékeihez."
    else:
        style_instruction = "Írj friss, kreatív irányban — csak a márkaértékeket tartsd meg, a megszokott szerkezetet ne."

    mood_text = ", ".join(MOOD_LABELS.get(m, m) for m in moods) if moods else "nincs megadva"
    brand = load_vates_urls()
    system = (
        "A Vates (vates.hu) magyar, művészeti ihletésű ruhamárka hírlevélírója vagy.\n\n"
        f"MÁRKA-ALAPOK: {'; '.join(brand['brand_facts'])}\n\n"
        f"VATES STÍLUSPROFIL:\n{style_profile}\n\n"
        f"STÍLUSKÖVETÉS (csúszka {adherence}/100): {style_instruction}\n"
        f"HANGULAT: {mood_text}\n\n"
        "KÖTELEZŐ SZABÁLYOK:\n"
        "- Magyarul írj, közvetlen tegeződéssel (te), a márkához illő emoji-használattal.\n"
        "- NE írj megszólítást (a 'Szia X!' a sablonban fixen szerepel), rögtön a történettel kezdj.\n"
        "- Félkövér kiemelés markdown jelöléssel: **így**.\n"
        "- A törzs 4-7 rövid, középre zárt bekezdés legyen, bekezdések között üres sor.\n"
        "- Tárgy max. 60 karakter, előnézeti szöveg max. 90 karakter.\n"
        "- CSAK valid JSON-t adj vissza, pontosan ezekkel a kulcsokkal: "
        '"subject", "preview_text", "body".'
    )
    user = f"Kampány témája / brief: {topic}"
    if notes:
        user += f"\n\nTovábbi instrukciók az operátortól: {notes}"
    messages = [{"role": "user", "content": user}]
    if previous and feedback:
        messages += [
            {"role": "assistant", "content": json.dumps(previous, ensure_ascii=False)},
            {"role": "user", "content": f"Generáld újra a következő visszajelzés alapján: {feedback}"},
        ]
    resp = _client().messages.create(
        model=MODEL, max_tokens=2000, system=system, messages=messages,
    )
    result = _extract_json(resp.content[0].text)
    result["subject"] = result.get("subject", "")[:60]
    result["preview_text"] = result.get("preview_text", "")[:90]
    return result


# ---------------------------------------------------------------------------
# Linkajánlás
# ---------------------------------------------------------------------------

def suggest_links(body_text):
    """3-5 horgonyszöveg + vates.hu URL javaslat a kész szöveghez."""
    data = load_vates_urls()
    url_list = "\n".join(
        f"- {c['url']} — {c['name']}: {c['theme']}"
        for c in data["collections"] + data["pages"]
    )
    prompt = (
        "Az alábbi magyar hírlevélszöveghez javasolj 3-5 linket.\n\n"
        f"HÍRLEVÉL SZÖVEGE:\n{body_text}\n\n"
        f"VÁLASZTHATÓ VATES.HU URL-EK:\n{url_list}\n\n"
        "Szabályok:\n"
        "- A horgonyszöveg (anchor) SZÓ SZERINT, karakterre pontosan szerepeljen a szövegben.\n"
        "- A kampány fő kollekciójára mutató, legfontosabb linknél \"highlight\": true "
        "(ez narancs kiemelést kap), a többinél false.\n"
        "- Adj meg egy \"header_href\" kulcsot is: a header képhez tartozó fő kollekció URL-je.\n"
        "- CSAK valid JSON-t adj vissza: "
        '{"header_href": "...", "links": [{"anchor": "...", "url": "...", '
        '"reason": "rövid magyar indoklás", "highlight": true/false}]}'
    )
    resp = _client().messages.create(
        model=MODEL, max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    result = _extract_json(resp.content[0].text)
    # csak vates.hu linkeket engedünk át
    result["links"] = [
        l for l in result.get("links", []) if is_vates_url(l.get("url", ""))
    ]
    if not is_vates_url(result.get("header_href", "")):
        result["header_href"] = "https://vates.hu/"
    return result


def is_vates_url(url):
    return bool(re.match(r"^https?://(www\.)?vates\.hu(/|$)", url or ""))


# ---------------------------------------------------------------------------
# Képek: base64 segéd
# ---------------------------------------------------------------------------

def _image_to_b64(path, max_size=512):
    img = Image.open(path)
    img = img.convert("RGB")
    img.thumbnail((max_size, max_size))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return base64.standard_b64encode(buf.getvalue()).decode()


def _image_content(path, max_size=512):
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": _image_to_b64(path, max_size),
        },
    }


# ---------------------------------------------------------------------------
# Vizuális stílusprofil a referencia headerekből
# ---------------------------------------------------------------------------

def load_visual_cache():
    if os.path.exists(VISUAL_CACHE_FILE):
        with open(VISUAL_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def build_visual_style_profile(reference_dir):
    files = sorted(
        f for f in os.listdir(reference_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    )[:50]
    if not files:
        profile = ("Nincs referencia header kép. Általános irányelv: 600x400-as "
                   "lifestyle/termékfotó, fehér, nagybetűs DIN headline alul.")
        with open(VISUAL_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"profile": profile, "count": 0}, f, ensure_ascii=False)
        return profile
    content = []
    for f in files[:20]:  # 20 kép elég a profilhoz, kontextus-kímélő
        content.append(_image_content(os.path.join(reference_dir, f), max_size=400))
    content.append({
        "type": "text",
        "text": (
            "Ezek a Vates hírlevelek korábbi header képei (600x400). Készíts "
            "vizuális stílusprofilt magyarul: tipikus kompozíció (téma- és "
            "szövegelhelyezés), színpaletta-tendenciák, hangulat és fotós stílus, "
            "szövegkezelés (méret, súly, pozíció). Tömören, listaszerűen."
        ),
    })
    resp = _client().messages.create(
        model=MODEL, max_tokens=1000,
        messages=[{"role": "user", "content": content}],
    )
    profile = resp.content[0].text
    with open(VISUAL_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"profile": profile, "count": len(files)}, f, ensure_ascii=False, indent=1)
    return profile


# ---------------------------------------------------------------------------
# Headline-variánsok az operátor által feltöltött fotóhoz
# ---------------------------------------------------------------------------

def generate_headline_variants(body_text, photo_path, visual_profile):
    """A feltöltött fotóhoz 3 különböző headline + pozíció variáns.

    Visszatérés: [{"headline", "position", "reason"}] (pontosan 3).
    """
    content = [
        _image_content(photo_path, max_size=800),
        {
            "type": "text",
            "text": (
                f"HÍRLEVÉL SZÖVEGE:\n{body_text}\n\n"
                f"VIZUÁLIS STÍLUSPROFIL (korábbi Vates headerek alapján):\n{visual_profile}\n\n"
                "A fenti fotóból készül a hírlevél header képe (600x400). Adj "
                "3 KÜLÖNBÖZŐ headline-variánst, eltérő megközelítéssel (pl. "
                "érzelmi horog / termékfókusz / játékos-ütős). Mindegyikhez:\n"
                "- ütős, NAGYBETŰS magyar headline, max 5-7 szó (headline)\n"
                "- a fotó kompozíciója alapján a szöveg helye (position): "
                "\"bottom-left\", \"bottom-center\", \"bottom-right\", "
                "\"top-left\" vagy \"top-center\" — oda tedd, ahol nem takar "
                "fontos képi elemet és jól olvasható\n"
                "- rövid magyar indoklás (reason)\n\n"
                "CSAK valid JSON-t adj vissza: "
                '[{"headline": "...", "position": "bottom-left", "reason": "..."}]'
            ),
        },
    ]
    resp = _client().messages.create(
        model=MODEL, max_tokens=1000,
        messages=[{"role": "user", "content": content}],
    )
    picks = _extract_json(resp.content[0].text)
    results = []
    for p in picks[:3]:
        if p.get("headline"):
            results.append({
                "headline": p["headline"].upper(),
                "position": p.get("position", "bottom-left"),
                "reason": p.get("reason", ""),
            })
    return results
