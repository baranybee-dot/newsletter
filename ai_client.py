"""Copy-paste híd: az AI-hívások helyett a program promptokat állít össze,
amiket az operátor a saját Claude-előfizetésébe (claude.ai) másol, majd a
választ visszamásolja. Így nincs szükség ANTHROPIC_API_KEY-re és nincs API-költség.

Ez a modul csak prompt-építőket és válasz-értelmezőket tartalmaz —
semmilyen hálózati hívást nem indít.
"""

import json
import os
import re

STYLE_CACHE_FILE = "style_cache.json"
URLS_FILE = os.path.join("data", "vates_urls.json")

MOOD_LABELS = {
    "playful": "játékos",
    "emotional": "érzelmes",
    "urgent": "sürgető",
    "informational": "informatív",
    "nostalgic": "nosztalgikus",
    "bold": "merész",
}

# Statikus vizuális stílusleírás a Vates korábbi headereiből — ezt fűzzük a
# header-felirat promptba, hogy az operátor Claude-ja tudja a márka képi stílusát.
VISUAL_STYLE_PROFILE = (
    "A Vates header képek 600x400-as, meleg tónusú lifestyle- vagy termékfotók, "
    "természetes fénnyel. A felirat fehér, NAGYBETŰS, vastag DIN betűtípus, "
    "általában a kép alján (bottom-left vagy bottom-center), néha felül. "
    "A headline rövid és ütős (3-6 szó), a kollekció témájához illő hangulattal "
    "(irodalom, retró mese, nyár, művészet stb.). A szöveg jól olvasható, nem "
    "takar fontos képi elemet."
)


def _extract_json(text):
    """JSON kinyerése a beillesztett válaszból (tűri a ```json blokkot is)."""
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1)
    # a legkorábbi nyitó zárójel ({ vagy [) a kezdet, a legkésőbbi záró a vég
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    end = max(text.rfind("}"), text.rfind("]"))
    if not starts or end == -1:
        raise ValueError("A beillesztett szövegben nem található JSON.")
    return json.loads(text[min(starts):end + 1])


def load_vates_urls():
    with open(URLS_FILE, encoding="utf-8") as f:
        return json.load(f)


def is_vates_url(url):
    return bool(re.match(r"^https?://(www\.)?vates\.hu(/|$)", url or ""))


# ---------------------------------------------------------------------------
# Stílusprofil (egyszeri, copy-paste híddal)
# ---------------------------------------------------------------------------

def load_style_cache():
    if os.path.exists(STYLE_CACHE_FILE):
        with open(STYLE_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_style_profile(profile_text, corpus_size=None):
    profile_text = (profile_text or "").strip()
    with open(STYLE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"profile": profile_text, "corpus_size": corpus_size},
                  f, ensure_ascii=False, indent=1)
    return profile_text


def build_style_analysis_prompt(corpus):
    """Prompt, amit az operátor a Claude-chatjébe másol a stílusprofil felépítéséhez."""
    samples = []
    for item in corpus[:50]:
        samples.append(
            f"--- Kampány: {item['name']}\nTárgy: {item['subject']}\n"
            f"Előnézet: {item['preview_text']}\nTörzs:\n{item['body_text'][:2500]}"
        )
    return (
        "Az alábbiakban a Vates (vates.hu) magyar ruhamárka korábban elküldött "
        "hírlevelei találhatók. Elemezd a korpuszt, és készíts részletes, tömör, "
        "magyar nyelvű STÍLUSPROFILT, amit később hírlevélíráshoz használunk.\n\n"
        "A profil térjen ki:\n"
        "- tipikus mondathossz és ritmus\n"
        "- gyakori nyitóformulák (pl. \"Volt egy pillanat...\")\n"
        "- érzelmi horgok és storytelling-szerkezet\n"
        "- CTA-megfogalmazási konvenciók\n"
        "- félkövér kiemelések használata, tegeződés, emoji-gyakoriság és -elhelyezés\n"
        "- tárgymezők és előnézeti szövegek mintázatai\n\n"
        "A választ csak maga a stílusprofil legyen (nincs szükség bevezetőre).\n\n"
        + "\n\n".join(samples)
    )


# ---------------------------------------------------------------------------
# Szöveggenerálás (copy-paste híd)
# ---------------------------------------------------------------------------

def build_text_generation_prompt(topic, adherence, moods, notes, style_profile):
    """A teljes, egyben beilleszthető prompt a levélszöveg generálásához.

    Mivel a claude.ai chatben nincs külön rendszerprompt-mező, mindent egy
    blokkba fűzünk.
    """
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
    parts = [
        "Egy Vates (vates.hu) hírlevél szövegét írd meg az alábbi paraméterek alapján.",
        "",
        f"MÁRKA-ALAPOK: {'; '.join(brand['brand_facts'])}",
        "",
        "VATES STÍLUSPROFIL:",
        style_profile,
        "",
        f"STÍLUSKÖVETÉS (csúszka {adherence}/100): {style_instruction}",
        f"HANGULAT: {mood_text}",
        "",
        f"A KAMPÁNY TÉMÁJA / BRIEF: {topic}",
    ]
    if notes:
        parts.append(f"TOVÁBBI INSTRUKCIÓK: {notes}")
    parts += [
        "",
        "KÖTELEZŐ SZABÁLYOK:",
        "- Magyarul írj, közvetlen tegeződéssel (te), a márkához illő emoji-használattal.",
        "- NE írj megszólítást (a 'Szia X!' a sablonban fixen szerepel), rögtön a történettel kezdj.",
        "- Félkövér kiemelés markdown jelöléssel: **így**.",
        "- A törzs 4-7 rövid, középre zárt bekezdés legyen, bekezdések között üres sor.",
        "- Tárgy max. 60 karakter, előnézeti szöveg max. 90 karakter.",
        "",
        "A VÁLASZ pontosan ebben a formátumban legyen, más szöveg nélkül:",
        "",
        "TÁRGY: <a tárgysor egy sorban>",
        "ELŐNÉZET: <az előnézeti szöveg egy sorban>",
        "TÖRZS:",
        "<a levél törzse — lehet többsoros, **félkövér** jelöléssel>",
    ]
    return "\n".join(parts)


def _label_value(text, labels):
    """Egysoros érték egy 'CÍMKE:' után."""
    for lab in labels:
        m = re.search(rf"(?im)^\s*{lab}\s*:\s*(.+)$", text)
        if m:
            return m.group(1).strip()
    return None


def _body_after(text, labels):
    """Minden, ami a 'CÍMKE:' után jön, a szöveg végéig (többsoros)."""
    for lab in labels:
        m = re.search(rf"(?is){lab}\s*:\s*(.+)", text)
        if m:
            return m.group(1).strip()
    return None


def parse_text_response(pasted):
    """A beillesztett Claude-válaszból kinyeri a subject/preview_text/body mezőket.

    Elsődlegesen a címkézett (TÁRGY / ELŐNÉZET / TÖRZS) formátumot várja, ami
    sortörést és idézőjelet is elvisel; tartalékként a régi JSON formátumot.
    """
    text = (pasted or "").strip()
    # esetleges kódblokk-keretek eltávolítása
    text = re.sub(r"```[a-zA-Z]*", "", text).strip()

    subject = _label_value(text, ["TÁRGY", "TARGY", "SUBJECT"])
    preview = _label_value(text, ["ELŐNÉZET", "ELONEZET", "PREVIEW TEXT", "PREVIEW"])
    body = _body_after(text, ["TÖRZS", "TORZS", "BODY"])
    if body:
        return {
            "subject": (subject or "").strip()[:60],
            "preview_text": (preview or "").strip()[:90],
            "body": body,
        }

    # tartalék: régi JSON formátum
    try:
        result = _extract_json(text)
        if isinstance(result, dict) and "body" in result:
            return {
                "subject": (result.get("subject") or "").strip()[:60],
                "preview_text": (result.get("preview_text") or "").strip()[:90],
                "body": (result.get("body") or "").strip(),
            }
    except (ValueError, json.JSONDecodeError):
        pass
    raise ValueError("Nem találom a TÁRGY / ELŐNÉZET / TÖRZS részeket a válaszban.")


# ---------------------------------------------------------------------------
# Header headline (copy-paste híd, fotóval)
# ---------------------------------------------------------------------------

def build_headline_prompt(body_text):
    """Prompt a header-feliratokhoz. Az operátor a fotót is feltölti a chatbe."""
    return (
        "Egy Vates hírlevél header képéhez kérek feliratokat. A header fotót "
        "FELTÖLTÖTTEM EBBE A BESZÉLGETÉSBE — nézd meg a kompozícióját.\n\n"
        f"A HÍRLEVÉL SZÖVEGE:\n{body_text}\n\n"
        f"A VATES HEADEREK VIZUÁLIS STÍLUSA:\n{VISUAL_STYLE_PROFILE}\n\n"
        "Adj 3 KÜLÖNBÖZŐ feliratötletet (headline), eltérő megközelítéssel "
        "(pl. érzelmi horog / termékfókusz / játékos-ütős). Mindegyikhez:\n"
        "- ütős, NAGYBETŰS magyar headline, max 5-7 szó (headline)\n"
        "- a fotó kompozíciója alapján a szöveg helye (position): \"bottom-left\", "
        "\"bottom-center\", \"bottom-right\", \"top-left\" vagy \"top-center\" — "
        "oda, ahol nem takar fontos képi elemet és jól olvasható\n"
        "- a felirat helye (POZÍCIÓ): bottom-left, bottom-center, bottom-right, "
        "top-left vagy top-center — oda, ahol nem takar fontos képi elemet\n\n"
        "A VÁLASZ pontosan 3 sor legyen, más szöveg nélkül, ebben a formában:\n"
        "FELIRAT: <NAGYBETŰS felirat> | POZÍCIÓ: bottom-left"
    )


VALID_POSITIONS = ("bottom-left", "bottom-center", "bottom-right", "top-left", "top-center")


def parse_headline_response(pasted):
    """A beillesztett válaszból kinyeri a 3 feliratot.

    Több formátumot is elvisel: JSON, címkézett sorok (FELIRAT: ... | POZÍCIÓ: ...),
    vagy egyszerű soronkénti feliratok.
    """
    text = (pasted or "").strip()

    # 1) JSON, ha úgy érkezett
    try:
        picks = _extract_json(text)
        if isinstance(picks, dict):
            picks = picks.get("headlines") or picks.get("variants") or [picks]
        out = []
        for p in picks[:3]:
            headline = (p.get("headline") or "").strip()
            if not headline:
                continue
            position = p.get("position", "bottom-left")
            if position not in VALID_POSITIONS:
                position = "bottom-left"
            out.append({"headline": headline.upper(), "position": position,
                        "reason": (p.get("reason") or "").strip()})
        if out:
            return out
    except (ValueError, json.JSONDecodeError, AttributeError, TypeError):
        pass

    # 2) soronkénti formátum — a megbízható sorokat preferáljuk
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    labeled = [l for l in lines if re.search(r"(?i)felirat\s*:|headline\s*:|bottom-|top-", l)]
    numbered = [l for l in lines if re.match(r"^\s*(\d+[.)]|[-*•])\s+", l)]
    plain = [l for l in lines if not l.endswith(":")]
    candidates = labeled or numbered or plain

    results = []
    for line in candidates:
        pm = re.search(r"(bottom-left|bottom-center|bottom-right|top-left|top-center)", line, re.I)
        position = pm.group(1).lower() if pm else "bottom-left"
        headline = re.split(r"\|", line)[0]
        headline = re.sub(r"^\s*(\d+[.)]|[-*•])\s+", "", headline)  # vezető listajelölő
        headline = re.sub(r"(?i)^\s*(FELIRAT|HEADLINE|CÍM)\s*:\s*", "", headline)
        headline = headline.strip().strip("\"'„”“").strip()
        if headline:
            results.append({"headline": headline.upper(), "position": position, "reason": ""})
        if len(results) == 3:
            break
    return results
