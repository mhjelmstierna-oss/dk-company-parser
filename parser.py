"""
DK Company PDF parser - deterministic column alignment via pdfplumber.

Stödjer både "Packlista" och "Orderbekräftelse" från DK Company Sweden AB.
Produktrader identifieras via positionell matchning mot storlekshuvud
istället för att förlita sig på textmarkörer som "Stk".
"""
import pdfplumber
import re
from collections import defaultdict


SAME_ROW_TOL = 2.0     # pixel-tolerans for att ord anses pa samma rad
COL_MATCH_TOL = 10.0   # max pixelavstand fran kvantitets-x till storlekshuvuds-x


def _group_by_row(words, tol=SAME_ROW_TOL):
    rows = []
    for w in sorted(words, key=lambda x: (x["top"], x["x0"])):
        placed = False
        for row in rows:
            if abs(row[0]["top"] - w["top"]) <= tol:
                row.append(w)
                placed = True
                break
        if not placed:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda w: w["x0"])
    rows.sort(key=lambda r: r[0]["top"])
    return rows


def _is_size_header_row(row):
    """En storlekshuvud-rad: >=3 numeriska ord, alla 1-3 siffror, stigande."""
    if len(row) < 3:
        return False
    vals = []
    for w in row:
        if not re.match(r"^\d{1,3}$", w["text"]):
            return False
        vals.append(int(w["text"]))
    # Stigande ordning
    return all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))


def _nearest_size(size_headers, x):
    best = None
    best_dist = None
    for s in size_headers:
        sx = (s["x0"] + s["x1"]) / 2
        d = abs(sx - x)
        if best_dist is None or d < best_dist:
            best = s
            best_dist = d
    return best, best_dist


def _parse_price(text):
    """Svenskt format: 1.100,00 eller 463,00"""
    try:
        return float(text.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _extract_order_number(rows):
    """Hitta ordernummer genom att leta efter rad med 'Ordre nr.'"""
    for i, row in enumerate(rows):
        row_text = " ".join(w["text"].lower() for w in row)
        if re.search(r"\bordre\s*nr\b", row_text):
            # Kan vara pa samma rad (packlista) eller nasta rad (orderbekraftelse)
            # Forsok nasta 1-2 rader, ta SISTA rena 6-7 siffror pa raden
            for j in range(i + 1, min(i + 3, len(rows))):
                nums = [w["text"] for w in rows[j] if re.match(r"^\d{5,8}$", w["text"])]
                if nums:
                    # Sista numret pa raden ar "Ordre nr."-kolumnen
                    return nums[-1]
    return None


def _is_product_row(row, size_headers):
    """En produktrad har minst en kvantitet (numerisk) positionerat under ett storlekshuvud."""
    for w in row:
        if re.match(r"^\d+$", w["text"]):
            cx = (w["x0"] + w["x1"]) / 2
            _, dist = _nearest_size(size_headers, cx)
            if dist is not None and dist <= COL_MATCH_TOL:
                return True
    return False


def _parse_product_row(row, size_headers):
    """Extrahera colorcode, colorname, qty_per_size, row_total, priser fran en rad."""
    qty_per_size = {}
    # Hitta alla ord som ligger under ett storlekshuvud (= kvantiteter)
    qty_indices = set()
    for idx, w in enumerate(row):
        if re.match(r"^\d+$", w["text"]):
            cx = (w["x0"] + w["x1"]) / 2
            size, dist = _nearest_size(size_headers, cx)
            if dist is not None and dist <= COL_MATCH_TOL:
                qty_per_size[size["text"]] = int(w["text"])
                qty_indices.add(idx)

    if not qty_per_size:
        return None

    # Ord FORE forsta kvantiteten ar colorcode + colorname
    first_qty_idx = min(qty_indices)
    prefix = row[:first_qty_idx]

    color_code = None
    color_name_parts = []
    for w in prefix:
        if color_code is None and re.match(r"^\d{4,}$", w["text"]):
            color_code = w["text"]
        else:
            # Ta med bade bokstaver och siffror som tillhor fargnamn (t.ex. "Oatmeal 32")
            color_name_parts.append(w["text"])
    color_name = " ".join(color_name_parts).strip()

    # Ord EFTER sista kvantiteten: row_total, price, rek.pris, belopp
    last_qty_idx = max(qty_indices)
    suffix = row[last_qty_idx + 1 :]
    # Ta bort "Stk"-ord om det finns
    suffix = [w for w in suffix if w["text"] != "Stk"]

    # row_total: hitta siffran i suffix som matchar summan av kvantiteter.
    # Packlista har "Rabat"-kolumn (t.ex. "40") foljt av antal, orderbekraftelse
    # har totalen direkt. Genom att matcha mot summan valjer vi ratt kolumn.
    expected_total = sum(qty_per_size.values())
    row_total = None
    for w in suffix:
        if re.match(r"^\d+$", w["text"]) and int(w["text"]) == expected_total:
            row_total = int(w["text"])
            break
    # Fallback: om ingen matchar, ta forsta rena siffran i suffix
    if row_total is None:
        for w in suffix:
            if re.match(r"^\d+$", w["text"]):
                row_total = int(w["text"])
                break

    # Priser = ord med "," i suffix
    price_words = [w["text"] for w in suffix if "," in w["text"]]
    purchase_price = None
    recommended_price = None
    # I bada format har vi rek.pris och ink.pris. Raknar bakifran:
    # Orderbekraftelse: [total_qty, ink.pris, rek.pris, belopp]
    # Packlista:        [rek.pris, ink.pris, rabat?, antal, "Stk"]
    # Enklast: forsta priset ar "Ink.pris" eller "Rek.pris" beroende pa layout.
    # For robust handling, spara alla och valj senare.
    parsed_prices = [_parse_price(p) for p in price_words]
    parsed_prices = [p for p in parsed_prices if p is not None]

    return {
        "color_code": color_code,
        "color_name": color_name,
        "qty_per_size": qty_per_size,
        "row_total": row_total,
        "prices": parsed_prices,
    }


def parse_dk_company(pdf_path):
    products = []
    order_number = None
    supplier = "DK Company"

    with pdfplumber.open(pdf_path) as pdf:
        all_rows = []
        for page in pdf.pages:
            words = page.extract_words()
            rows = _group_by_row(words)
            all_rows.extend(rows)

        if order_number is None:
            order_number = _extract_order_number(all_rows)

        # Iterera: hitta [SKU-rad] -> [size-header] -> [produktrader...] block
        i = 0
        while i < len(all_rows):
            row = all_rows[i]
            # En SKU-rad: forsta ordet ar 8-siffrigt, och raden innehaller alfabetiska ord (item name)
            if (
                row
                and re.match(r"^\d{8}$", row[0]["text"])
                and row[0]["text"] != "92000000"  # fragt
            ):
                sku = row[0]["text"]
                # Bygg item-namn: bokstavliga ord utan datum/prislike delar
                name_parts = []
                for w in row[1:]:
                    t = w["text"]
                    # Skippa datum och "Rek.pris"-liknande fragment
                    if re.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}", t):
                        continue
                    if re.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}/\d{1,2}\.\d{1,2}\.\d{2,4}", t):
                        continue
                    if "," in t or "/" in t:
                        continue
                    if re.match(r"^\d{2,}$", t):
                        # Kort nummer efter namn (t.ex. "149" i "LaraMWPant 149")
                        # Ta med som del av namnet
                        name_parts.append(t)
                        continue
                    name_parts.append(t)
                current_name = " ".join(name_parts).strip()
                current_sku = sku

                # Leta efter storlekshuvud i naera 5 rader
                size_header = None
                j = i + 1
                while j < len(all_rows) and j < i + 6:
                    if _is_size_header_row(all_rows[j]):
                        size_header = all_rows[j]
                        break
                    j += 1
                if size_header is None:
                    i += 1
                    continue

                # Produktrader efter size_header tills nasta SKU-rad eller totalrad
                k = j + 1
                while k < len(all_rows):
                    prow = all_rows[k]
                    # Ny produkt? SKU-rad?
                    if prow and re.match(r"^\d{8}$", prow[0]["text"]) and prow[0]["text"] != "92000000":
                        break
                    # Totalrad?
                    prow_text = " ".join(w["text"].lower() for w in prow)
                    if re.search(r"total\s+antal|transport|tran\.?\s*s\.?\s*p", prow_text):
                        break
                    # Ar det en produktrad?
                    if _is_product_row(prow, size_header):
                        parsed = _parse_product_row(prow, size_header)
                        if parsed:
                            # Bestam priser: forsta priset i suffixen ar ofta "Ink.pris" (inkopspris)
                            # Vi valjer det LAGSTA priset som purchase och det HOGSTA som recommended
                            prices = parsed["prices"]
                            purchase_price = None
                            recommended_price = None
                            if len(prices) >= 2:
                                purchase_price = min(prices[:2])
                                recommended_price = max(prices[:2])
                            elif len(prices) == 1:
                                purchase_price = prices[0]

                            for size_text, qty in parsed["qty_per_size"].items():
                                products.append({
                                    "sku": current_sku,
                                    "name": current_name,
                                    "color": parsed["color_name"],
                                    "size": size_text,
                                    "quantity": qty,
                                    "purchase_price": purchase_price,
                                    "recommended_price": recommended_price,
                                    "_pdf_row_total": parsed["row_total"],
                                    "_color_code": parsed["color_code"],
                                })
                    k += 1
                i = k
                continue
            i += 1

    return {
        "supplier": supplier,
        "order_number": order_number,
        "products": products,
    }


if __name__ == "__main__":
    import sys
    import json
    pdf = sys.argv[1]
    result = parse_dk_company(pdf)
    print(json.dumps(result, indent=2, ensure_ascii=False))
