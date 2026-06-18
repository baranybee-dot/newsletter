# Vates hírlevél-automatizáló

Webes eszköz Klaviyo email kampányok összeállítására és időzítésére a Vates
(vates.hu) márkához — 6 lépéses varázslóval, **copy-paste AI-híddal**.

## Az AI copy-paste híd

Az alkalmazás nem hív közvetlenül AI-t, így **nincs szükség ANTHROPIC_API_KEY-re
és nincs API-költség**. Ahol AI segít (szöveg, header-feliratok), ott a program
összeállít egy promptot, amit az operátor a saját Claude-előfizetésébe
(claude.ai) másol, majd a választ visszailleszti. A program a választ értelmezi
és feldolgozza.

## Lépések

1. **Szöveg generálása** — a program promptot ad a korábbi 50 kampányból tanult Vates-stílusprofillal; az operátor a Claude-ba másolja, a JSON választ visszailleszti, majd szerkesztheti
2. **Szöveg és linkek** — az operátor kézzel rendel vates.hu linkeket a szöveghez (legördülő URL-segítséggel); csak vates.hu domain engedett
3. **Header kép** — az operátor feltölt egy fotót, ugyanazt a fotót a Claude-chatjébe is, kap 3 feliratötletet, amiket visszailleszt; Pillow-kompozit (600×400)
4. **Finomhangolás** — headline, betűméret, pozíció, szín, élő előnézettel
5. **Időzítés és célközönség** — Klaviyo listák/szegmensek, küldés mindig magyar idő (Europe/Budapest) szerint időzítve
6. **Végső ellenőrzés** — beküldés a Klaviyo-ba (kép feltöltés → sablon klónozás → tartalom injektálás → kampány létrehozás → időzítés), hiba esetén teljes rollback

A stílusprofil felépítése egyszeri, szintén copy-paste híddal (`/admin/style`):
a program kinyeri a Klaviyo-ból az 50 korábbi levelet, promptot ad, az operátor
a Claude válaszát (a stílusprofilt) visszailleszti és elmentődik.

## Futtatás

```bash
pip install -r requirements.txt
cp .env.example .env   # töltsd ki a kulcsokat
python app.py          # fejlesztéshez
gunicorn app:app       # éles (Railway a Procfile alapján)
```

## Környezeti változók

Lásd `.env.example`. Kötelező: `KLAVIYO_API_KEY`, `KLAVIYO_TEMPLATE_ID`,
`FLASK_SECRET_KEY`. (Anthropic-kulcs **nem** kell — lásd a copy-paste hidat.)

## Feltöltendő eszközök (deploy előtt)

- `static/fonts/DINPro-Bold.otf` vagy `DIN2014-Bold.ttf` — amíg hiányzik, helyettesítő fonttal dolgozik

> A Railway fájlrendszere ephemeral: a `style_cache.json` és a session-képek
> (köztük a feltöltött fotók) deploykor törlődnek. A stílusprofilt deploy után
> egyszer újra fel kell építeni (`/admin/style`).

## Megjegyzések

- A master sablon (`KLAVIYO_TEMPLATE_ID`) drag-and-drop típusú kell legyen; az
  app a 600×400-as kép blokkot és a `Szia {{ first_name }}` szövegblokkot írja át.
- A kampány sosem indul azonnal — mindig statikus időzítéssel jön létre.
- Minden link csak vates.hu domainre mutathat (a UI kikényszeríti).
