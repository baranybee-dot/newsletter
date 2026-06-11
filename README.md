# Vates hírlevél-automatizáló

Webes eszköz Klaviyo email kampányok összeállítására és időzítésére a Vates
(vates.hu) márkához — AI-asszisztált, 6 lépéses varázslóval.

## Lépések

1. **Szöveg generálása** — Claude a korábbi 50 kampányból tanult Vates-stílusban ír (stíluskövetés-csúszka, hangulatcímkék)
2. **Szöveg és linkek** — AI-javasolt vates.hu linkek, kézi szerkesztéssel
3. **Header kép** — a fotókönyvtárból AI által választott 3 fotó + headline, Pillow-kompozit (600×400)
4. **Finomhangolás** — headline, betűméret, pozíció, szín, élő előnézettel
5. **Időzítés és célközönség** — Klaviyo listák/szegmensek, küldés mindig magyar idő (Europe/Budapest) szerint időzítve
6. **Végső ellenőrzés** — beküldés a Klaviyo-ba (kép feltöltés → sablon klónozás → tartalom injektálás → kampány létrehozás → időzítés), hiba esetén teljes rollback

## Futtatás

```bash
pip install -r requirements.txt
cp .env.example .env   # töltsd ki a kulcsokat
python app.py          # fejlesztéshez
gunicorn app:app       # éles (Railway a Procfile alapján)
```

## Környezeti változók

Lásd `.env.example`. Kötelező: `KLAVIYO_API_KEY`, `ANTHROPIC_API_KEY`,
`KLAVIYO_TEMPLATE_ID`, `FLASK_SECRET_KEY`.

## Feltöltendő eszközök (deploy előtt)

- `static/fonts/DINPro-Bold.otf` vagy `DIN2014-Bold.ttf` — amíg hiányzik, helyettesítő fonttal dolgozik
- `static/reference_headers/` — 50 referencia header kép a vizuális stílusprofilhoz
- `static/photo_library/` — a választható fotók (vagy `PHOTO_LIBRARY_PATH` env változó)

> A Railway fájlrendszere ephemeral: a fotókat a repóba kell commitolni, vagy
> külső tárhelyről (S3/CDN) kell kiszolgálni. A `style_cache.json` és a
> session-képek deploykor törlődnek — ezek újragenerálhatók.

## Megjegyzések

- A master sablon (`KLAVIYO_TEMPLATE_ID`) drag-and-drop típusú kell legyen; az
  app a 600×400-as kép blokkot és a `Szia {{ first_name }}` szövegblokkot írja át.
- A kampány sosem indul azonnal — mindig statikus időzítéssel jön létre.
- Minden link csak vates.hu domainre mutathat (a UI kikényszeríti).
