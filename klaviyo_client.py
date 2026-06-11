"""Minden Klaviyo API hívás egy helyen.

A sablon a fiókban SYSTEM_DRAGGABLE (drag-and-drop) típusú, ezért a
tartalmat a strukturált `definition`-ön keresztül írjuk át:
  - header kép blokk: 600x400-as image blokk (src + href + alt_text)
  - törzs blokk: az a text blokk, ami a "Szia {{ first_name }}" köszöntést tartalmazza
"""

import html as html_lib
import os
import re
import time
from html.parser import HTMLParser

import requests

BASE_URL = "https://a.klaviyo.com/api"
REVISION = "2025-07-15"
RATE_LIMIT_SLEEP = 0.3

ARIAL = "Arial, 'Helvetica Neue', Helvetica, sans-serif"
P_STYLE = (
    "text-align: center; color: rgb(0, 0, 0); "
    f"font-family: {ARIAL}; font-size: 14px;"
)
GREETING_HTML = (
    '<h3 style="text-align: center;">'
    f'<span style="color: rgb(0, 0, 0); font-family: {ARIAL};">'
    "Szia {{ first_name|default:'' }}!</span></h3>"
)
HIGHLIGHT_COLOR = "rgb(226, 110, 6)"  # a Vates levelek narancs kiemelő színe


class KlaviyoError(Exception):
    pass


def _headers(extra=None):
    api_key = os.environ.get("KLAVIYO_API_KEY", "")
    headers = {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "revision": REVISION,
        "accept": "application/vnd.api+json",
    }
    if extra:
        headers.update(extra)
    return headers


def _request(method, path, json_body=None, params=None, files=None, data=None):
    time.sleep(RATE_LIMIT_SLEEP)
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    extra = {} if files else {"content-type": "application/vnd.api+json"}
    resp = requests.request(
        method, url, headers=_headers(extra), json=json_body,
        params=params, files=files, data=data, timeout=60,
    )
    if resp.status_code >= 400:
        try:
            detail = "; ".join(e.get("detail", "") for e in resp.json().get("errors", []))
        except Exception:
            detail = resp.text[:500]
        raise KlaviyoError(f"Klaviyo API hiba ({resp.status_code}, {method} {path}): {detail}")
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()


# ---------------------------------------------------------------------------
# Stílustanuláshoz: elküldött kampányok szövegei
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    SKIP_TAGS = {"style", "script", "head", "title"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag in ("p", "br", "h1", "h2", "h3", "div", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(html):
    parser = _TextExtractor()
    parser.feed(html)
    text = html_lib.unescape("".join(parser.parts))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def fetch_sent_campaign_corpus(limit=50):
    """A legutóbb elküldött email kampányok adatai a stílustanuláshoz.

    Visszatérés: lista, elemenként {name, subject, preview_text, body_text}.
    """
    corpus = []
    params = {
        "filter": "and(equals(messages.channel,'email'),equals(status,'Sent'))",
        "include": "campaign-messages",
        "fields[campaign]": "name,status,send_time",
        "sort": "-scheduled_at",
    }
    url = "/campaigns"
    while url and len(corpus) < limit:
        page = _request("GET", url, params=params)
        params = None  # a next link már tartalmazza
        included = {item["id"]: item for item in page.get("included", [])}
        for camp in page.get("data", []):
            if len(corpus) >= limit:
                break
            msg_refs = camp.get("relationships", {}).get("campaign-messages", {}).get("data", [])
            for ref in msg_refs:
                msg = included.get(ref["id"])
                if not msg:
                    continue
                content = (msg.get("attributes", {}).get("definition", {}) or {}).get("content", {}) or {}
                tpl_ref = (msg.get("relationships", {}).get("template", {}) or {}).get("data") or {}
                body_text = ""
                if tpl_ref.get("id"):
                    try:
                        tpl = get_template(tpl_ref["id"])
                        body_text = extract_body_text_from_template(tpl)
                    except KlaviyoError:
                        pass
                corpus.append({
                    "name": camp["attributes"].get("name", ""),
                    "subject": content.get("subject", ""),
                    "preview_text": content.get("preview_text", ""),
                    "body_text": body_text,
                })
                break  # kampányonként egy üzenet elég
        url = (page.get("links") or {}).get("next")
    return corpus


def extract_body_text_from_template(template_data):
    """A sablon törzsszövege plain textként (a köszöntő text blokkból)."""
    definition = template_data.get("attributes", {}).get("definition")
    if definition:
        block = _find_body_text_block(definition)
        if block is not None:
            return html_to_text(block["data"].get("content", ""))
    html = template_data.get("attributes", {}).get("html") or ""
    return html_to_text(html)[:4000]


# ---------------------------------------------------------------------------
# Listák, szegmensek
# ---------------------------------------------------------------------------

def get_lists():
    return _paginate("/lists", {"fields[list]": "name,created"})


def get_segments():
    return _paginate("/segments", {"fields[segment]": "name,created"})


def _paginate(path, params):
    items, url = [], path
    while url:
        page = _request("GET", url, params=params)
        params = None
        for item in page.get("data", []):
            items.append({"id": item["id"], "name": item["attributes"].get("name", "")})
        url = (page.get("links") or {}).get("next")
    return items


# ---------------------------------------------------------------------------
# Sablon műveletek
# ---------------------------------------------------------------------------

def get_template(template_id):
    return _request("GET", f"/templates/{template_id}")["data"]


def clone_template(template_id, new_name):
    payload = {
        "data": {
            "type": "template",
            "id": template_id,
            "attributes": {"name": new_name},
        }
    }
    return _request("POST", "/template-clone", json_body=payload)["data"]


def delete_template(template_id):
    _request("DELETE", f"/templates/{template_id}")


def upload_image(filepath, name):
    """Kép feltöltése a Klaviyo képtárba (multipart). Visszaadja az image objektumot."""
    with open(filepath, "rb") as f:
        result = _request(
            "POST", "/image-upload",
            files={"file": (os.path.basename(filepath), f, "image/jpeg")},
            data={"name": name, "hidden": "false"},
        )
    return result["data"]


def _iter_blocks(definition):
    for section in definition.get("body", {}).get("sections", []) or []:
        for row in section.get("rows", []) or []:
            for column in row.get("columns", []) or []:
                for block in column.get("blocks", []) or []:
                    yield block


def _find_header_image_block(definition):
    """A 600x400-as, linkelt header kép blokk."""
    for block in _iter_blocks(definition):
        if block.get("type") != "image":
            continue
        styles = block.get("data", {}).get("styles", {}) or {}
        props = block.get("data", {}).get("properties", {}) or {}
        if styles.get("width") == 600 and styles.get("height") == 400:
            return block
        if props.get("src") and props.get("href") and "collections" in (props.get("href") or ""):
            return block
    return None


def _find_body_text_block(definition):
    for block in _iter_blocks(definition):
        if block.get("type") == "text" and "{{ first_name" in block.get("data", {}).get("content", ""):
            return block
    return None


def inject_template_content(template_id, image_url, image_alt, header_href, body_html):
    """A klónozott sablonba beírja a header képet és a törzs HTML-t."""
    template = get_template(template_id)
    definition = template.get("attributes", {}).get("definition")
    if not definition:
        raise KlaviyoError(
            "A sablon nem tartalmaz szerkeszthető definition-t — "
            "ellenőrizd, hogy a master sablon drag-and-drop típusú-e."
        )
    header_block = _find_header_image_block(definition)
    if header_block is None:
        raise KlaviyoError("Nem található a 600x400-as header kép blokk a sablonban.")
    body_block = _find_body_text_block(definition)
    if body_block is None:
        raise KlaviyoError("Nem található a törzs text blokk ('Szia {{ first_name }}') a sablonban.")

    props = header_block["data"]["properties"]
    props["src"] = image_url
    props["alt_text"] = image_alt
    props["href"] = header_href
    props.pop("asset_id", None)  # az új src nem a régi asset

    body_block["data"]["content"] = body_html

    payload = {
        "data": {
            "type": "template",
            "id": template_id,
            "attributes": {"definition": definition},
        }
    }
    _request("PATCH", f"/templates/{template_id}", json_body=payload)


# ---------------------------------------------------------------------------
# Törzs HTML építése a szerkesztett szövegből és linkekből
# ---------------------------------------------------------------------------

def build_body_html(body_text, links):
    """Plain text (markdown **bold** jelöléssel) -> a sablon formátumú HTML.

    links: [{"anchor": str, "url": str, "highlight": bool}, ...]
    A köszöntő sort ({{ first_name }}) fixen hozzáadjuk, a generált szöveg
    nem tartalmaz megszólítást.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", body_text) if p.strip()]
    out = [GREETING_HTML]
    for para in paragraphs:
        escaped = html_lib.escape(para, quote=False)
        # linkek beszúrása (leghosszabb horgony először, hogy ne legyen átfedés)
        for link in sorted(links or [], key=lambda l: -len(l["anchor"])):
            anchor_esc = html_lib.escape(link["anchor"], quote=False)
            if anchor_esc not in escaped:
                continue
            color = HIGHLIGHT_COLOR if link.get("highlight") else "rgb(0, 0, 0)"
            replacement = (
                f'<a target="_blank" rel="noopener noreferrer nofollow" '
                f'href="{html_lib.escape(link["url"])}" style="color: {color};">'
                f'<span style="color: {color}; font-family: {ARIAL}; font-size: 14px;">'
                f"<strong style=\"font-weight: 700;\">{anchor_esc}</strong></span></a>"
            )
            escaped = escaped.replace(anchor_esc, replacement, 1)
        # **félkövér** jelölés
        escaped = re.sub(
            r"\*\*(.+?)\*\*",
            r'<strong style="font-weight: 700;">\1</strong>',
            escaped,
        )
        out.append(f'<p style="{P_STYLE}">{escaped}</p>')
    return "".join(out)


# ---------------------------------------------------------------------------
# Kampány létrehozás és időzítés
# ---------------------------------------------------------------------------

def create_campaign(name, audience_ids, send_datetime_utc, subject, preview_text):
    """Vázlat kampány statikus küldési stratégiával (mindig időzített)."""
    payload = {
        "data": {
            "type": "campaign",
            "attributes": {
                "name": name,
                "audiences": {"included": audience_ids},
                "send_strategy": {
                    "method": "static",
                    "datetime": send_datetime_utc,
                    "options": {"is_local": False},
                },
                "send_options": {"use_smart_sending": True},
                "campaign-messages": {
                    "data": [
                        {
                            "type": "campaign-message",
                            "attributes": {
                                "definition": {
                                    "channel": "email",
                                    "content": {
                                        "subject": subject,
                                        "preview_text": preview_text,
                                    },
                                }
                            },
                        }
                    ]
                },
            },
        }
    }
    return _request("POST", "/campaigns", json_body=payload)


def get_campaign_message_id(campaign_response):
    included = campaign_response.get("included", [])
    for item in included:
        if item.get("type") == "campaign-message":
            return item["id"]
    refs = (
        campaign_response["data"]
        .get("relationships", {})
        .get("campaign-messages", {})
        .get("data", [])
    )
    if refs:
        return refs[0]["id"]
    raise KlaviyoError("Nem található campaign-message a létrehozott kampányban.")


def assign_template_to_message(message_id, template_id):
    payload = {
        "data": {
            "type": "campaign-message",
            "id": message_id,
            "relationships": {
                "template": {"data": {"type": "template", "id": template_id}}
            },
        }
    }
    _request("POST", "/campaign-message-assign-template", json_body=payload)


def schedule_campaign(campaign_id):
    """A kampányt időzítettre állítja (sosem azonnali küldés)."""
    payload = {"data": {"type": "campaign-send-job", "id": campaign_id}}
    _request("POST", "/campaign-send-jobs", json_body=payload)


def delete_campaign(campaign_id):
    _request("DELETE", f"/campaigns/{campaign_id}")


def submit_full_campaign(master_template_id, header_image_path, header_alt,
                         header_href, body_html, campaign_name, audience_ids,
                         send_datetime_utc, subject, preview_text):
    """A teljes beküldés egy tranzakcióként: hiba esetén rollback.

    Visszatérés: campaign_id sikeres időzítés után.
    """
    cloned_template_id = None
    campaign_id = None
    try:
        image = upload_image(header_image_path, f"header - {campaign_name}")
        image_url = image["attributes"]["image_url"]

        cloned = clone_template(master_template_id, campaign_name)
        cloned_template_id = cloned["id"]

        inject_template_content(
            cloned_template_id, image_url, header_alt, header_href, body_html
        )

        campaign_resp = create_campaign(
            campaign_name, audience_ids, send_datetime_utc, subject, preview_text
        )
        campaign_id = campaign_resp["data"]["id"]
        message_id = get_campaign_message_id(campaign_resp)

        assign_template_to_message(message_id, cloned_template_id)
        schedule_campaign(campaign_id)
        return campaign_id
    except Exception:
        # részleges beküldés tilos: takarítunk
        if campaign_id:
            try:
                delete_campaign(campaign_id)
            except Exception:
                pass
        if cloned_template_id:
            try:
                delete_template(cloned_template_id)
            except Exception:
                pass
        raise
