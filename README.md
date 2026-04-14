[README.md](https://github.com/user-attachments/files/26726037/README.md)
# DK Company PDF Parser

Liten webhook-tjänst som läser DK Company-packlistor och orderbekräftelser och returnerar strukturerad JSON med korrekt storlek/kvantitet-mappning via positionell PDF-analys.

## Endpoints

- `GET /` — hälsocheck
- `POST /parse` — tar emot PDF och returnerar JSON

### POST /parse

Antingen skicka PDF som multipart-fil:
```
curl -X POST https://dittnamn.onrender.com/parse \
  -H "x-api-key: DIN_NYCKEL" \
  -F "pdf=@orderconfirmation.pdf"
```

Eller som base64 i JSON-body:
```
{
  "pdf_base64": "JVBERi0xLjQK..."
}
```

### Respons
```
{
  "supplier": "DK Company",
  "order_number": "966529",
  "products": [
    {
      "sku": "10705563",
      "name": "MWGisva Pant",
      "color": "Light Fores Long",
      "size": "36",
      "quantity": 1,
      "purchase_price": 463.0,
      "recommended_price": 1300.0,
      "_pdf_row_total": 6,
      "_color_code": "109489"
    },
    ...
  ]
}
```

## Deploya på Render (gratis)

1. Skapa ett GitHub-repo och ladda upp följande filer:
   - `parser.py`
   - `server.py`
   - `requirements.txt`
   - `render.yaml`
2. Gå till https://render.com och skapa ett konto (gratis)
3. Klicka "New +" → "Blueprint"
4. Anslut ditt GitHub-konto och välj det repo du just skapade
5. Render läser `render.yaml` automatiskt och skapar tjänsten
6. När deploy är klar får du en URL, t.ex. `https://dk-company-parser.onrender.com`
7. Under "Environment" → kopiera värdet för `API_KEY` (auto-genererat)

> **Obs: Render free tier somnar efter 15 min utan trafik.** Första anropet efter inaktivitet tar ~30-60 sek. Det är OK för din arbetsflöde eftersom PDF:erna ändå bearbetas några gånger per dag.

## Lokal test

```bash
pip install -r requirements.txt
uvicorn server:app --port 8000
curl -X POST http://localhost:8000/parse -F "pdf=@test.pdf"
```
