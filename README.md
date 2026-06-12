# Vates hírlevél-automatizáló

Webes eszköz Klaviyo email kampányok összeállítására és időzítésére a Vates
(vates.hu) márkához — AI-asszisztált, 6 lépéses varázslóval.

## Lépések

1. **Szöveg generálása** — Claude a korábbi 50 kampányból tanult Vates-stílusban ír (stíluskövetés-csúszka, hangulatcímkék)
2. **Szöveg és linkek** — AI-javasolt vates.hu linkek, kézi szerkesztéssel
3. **Header kép** — az operátor feltölt egy fotót, abból az AI 3 headline-variánst készít, Pillow-kompozit (600×400)
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

> A Railway fájlrendszere ephemeral: a `style_cache.json` és a session-képek
> (köztük a feltöltött fotók) deploykor törlődnek — ezek újragenerálhatók,
> illetve a fotót az operátor kampányonként tölti fel.

## Megjegyzések

- A master sablon (`KLAVIYO_TEMPLATE_ID`) drag-and-drop típusú kell legyen; az
  app a 600×400-as kép blokkot és a `Szia {{ first_name }}` szövegblokkot írja át.
- A kampány sosem indul azonnal — mindig statikus időzítéssel jön létre.
- Minden link csak vates.hu domainre mutathat (a UI kikényszeríti).
