"""
Recolecta datos de composición de alimentos lácteos desde USDA FoodData
Central (https://fdc.nal.usda.gov/). Requiere una API key gratuita:
https://fdc.nal.usda.gov/api-key-signup

Ojo: el USDA describe el PRODUCTO TERMINADO (etiqueta nutricional, por 100 g).
No trae datos de proceso (pH, temperatura), raza de vaca ni región de origen;
esos vienen de los papers (tabla `observaciones`). Lo que sí se puede deducir
de la descripción e ingredientes (A2, orgánica, UHT, sin lactosa...) se extrae
en `atributos_producto`.
"""

import re
import time

import requests

USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

# Nutrientes por su código USDA (nutrientNumber), que es estable; el nombre
# cambia entre tipos de datos y "Energy" aparece tanto en kcal como en kJ.
KEY_NUTRIENTS = {
    "208": "energy_kcal",
    "203": "protein_g",
    "204": "fat_g",
    "606": "sat_fat_g",
    "205": "carbs_g",
    "269": "sugars_g",
    "213": "lactose_g",
    "255": "water_g",
    "601": "cholesterol_mg",
    "301": "calcium_mg",
    "305": "phosphorus_mg",
    "306": "potassium_mg",
    "307": "sodium_mg",
    "304": "magnesium_mg",
    "324": "vitamin_d_iu",
    "320": "vitamin_a_rae_ug",
    "418": "vitamin_b12_ug",
}

# (columna, [(valor, patrón regex)]): se asigna el primer valor cuyo patrón
# aparezca en la descripción o ingredientes; si ninguno aparece, "no_especificado".
# Las columnas de SOLO_DESCRIPCION ignoran los ingredientes (una leche con
# "cream" entre sus ingredientes sigue siendo leche).
REGLAS_ATRIBUTOS = [
    ("tipo_producto", [
        ("kefir", r"\bKEFIR\b"),
        ("yogur", r"\bYOG(H)?URTS?\b"),
        ("queso", r"\b(CHEESE|CHEDDAR|MOZZARELLA|PARMESAN|GOUDA|BRIE|FETA|COLBY|MONTEREY"
                  r"|PROVOLONE|RICOTTA|HAVARTI|GRUYERE|MUENSTER|CAMEMBERT|QUESO)\b"),
        ("mantequilla", r"\bBUTTER\b"),
        ("crema", r"\b(CREAM\b(?![ -]+(ON[ -]+)?TOP)|HALF (AND|&) HALF)"),
        ("leche_en_polvo", r"\b(DRY|POWDER(ED)?)\b"),
        ("leche", r"\bMILK\b"),
    ]),
    ("tipo_beta_caseina", [("A2", r"\bA2\b")]),
    ("especie_leche", [
        ("cabra", r"\bGOAT"),
        ("oveja", r"\b(SHEEP|EWE)"),
        ("bufala", r"\bBUFFALO"),
        ("vaca", r"\b(MILK|CHEESE|YOG(H)?URT|CREAM|BUTTER|KEFIR)\b"),
    ]),
    ("raza", [
        ("jersey", r"\bJERSEY"),
        ("guernsey", r"\bGUERNSEY"),
        ("holstein", r"\bHOLSTEIN"),
        ("pardo_suizo", r"\bBROWN SWISS"),
        ("ayrshire", r"\bAYRSHIRE"),
    ]),
    ("tratamiento_termico", [
        ("uht", r"\b(UHT|ULTRA[- ]HIGH)"),
        ("ultrapasteurizado", r"\bULTRA[- ]?PASTEURI[ZS]ED"),
        ("pasteurizado_lento", r"\b(VAT|LOW[- ]TEMP(ERATURE)?)[- ]PASTEURI[ZS]ED"),
        ("crudo", r"\bRAW (WHOLE |A2 )?MILK\b|\bUNPASTEURI[ZS]ED"),
        ("pasteurizado", r"\bPASTEURI[ZS]ED"),
    ]),
    ("nivel_grasa", [
        ("descremada", r"\b(SKIM|FAT[- ]FREE|NON[- ]?FAT|0%)"),
        ("baja_grasa", r"\b(LOW[- ]FAT|1%|1 ?PERCENT)"),
        ("semidescremada", r"\b(REDUCED[- ]FAT|2%|2 ?PERCENT)"),
        ("entera", r"\b(WHOLE|FULL[- ]FAT|3\.25%|4%)"),
    ]),
    ("homogeneizado", [
        ("no", r"\b(NON[- ]?HOMOGENI[ZS]ED|CREAM[ -]+(ON[ -]+)?TOP|CREAMLINE)"),
        ("si", r"\bHOMOGENI[ZS]ED"),
    ]),
    ("saborizada", [("si", r"\b(CHOCOLATE|COCOA|STRAWBERRY|VANILLA|BANANA|FLAVOU?RED|FRUIT|BERRY"
                            r"|PEACH|CHERRY|MANGO|HONEY|CARAMEL|COFFEE|MOCHA|LEMON|LIME|RASPBERRY|BLUEBERRY)")]),
    ("ultrafiltrada", [("si", r"\b(ULTRA[- ]?FILTERED|FAIRLIFE)")]),
    ("sin_lactosa", [("si", r"\b(LACTOSE[- ]FREE|LACTASE)")]),
    ("organico", [("si", r"\bORGANIC\b")]),
    ("pastoreo", [("si", r"\b(GRASS[- ]?FED|PASTURE[- ]?RAISED)")]),
    ("probioticos", [("si", r"\b(PROBIOTIC|LACTOBACILLUS|BIFIDOBACTERI|ACIDOPHILUS|LIVE (AND )?ACTIVE CULTURES)")]),
    ("fortificada_vit_d", [("si", r"\bVITAMIN D")]),
]

SOLO_DESCRIPCION = {"tipo_producto", "especie_leche", "nivel_grasa", "raza"}


# Subtipo: separa los productos comparables entre sí ("natural") de los que
# cambian la composición por su proceso o formulación. Se decide solo con la
# descripción; el primer patrón que coincida gana y si ninguno coincide es "natural".
SUBTIPOS = ["natural", "fermentada", "concentrada", "en_polvo", "modificada", "saborizada"]
REGLAS_SUBTIPO = [
    # Solo para leche: yogur y kéfir ya son fermentados por definición
    ("fermentada", r"\b(BUTTERMILK|CULTURED|FERMENTED)\b", {"leche"}),
    ("concentrada", r"\b(CONDENSED|EVAPORATED)\b", None),
    ("en_polvo", r"\b(DRY|DRIED|POWDER(ED)?)\b", None),
    ("modificada", r"\b(LOW SODIUM|PROTEIN MILK|ULTRA[- ]?FILTERED|FAIRLIFE|CALCIUM REDUCED|IMITATION)\b", None),
]


def subtipo_producto(description, tipo_producto, saborizada):
    if saborizada == "si":
        return "saborizada"
    texto = (description or "").upper()
    for subtipo, patron, solo_tipos in REGLAS_SUBTIPO:
        if (solo_tipos is None or tipo_producto in solo_tipos) and re.search(patron, texto):
            return subtipo
    return "natural"


def atributos_producto(description, ingredients):
    solo_descripcion = (description or "").upper()
    completo = f"{solo_descripcion} {(ingredients or '').upper()}"
    atributos = {}
    for columna, reglas in REGLAS_ATRIBUTOS:
        texto = solo_descripcion if columna in SOLO_DESCRIPCION else completo
        atributos[columna] = next(
            (valor for valor, patron in reglas if re.search(patron, texto)),
            "no_especificado",
        )
    atributos["subtipo"] = subtipo_producto(description, atributos["tipo_producto"], atributos["saborizada"])
    return atributos


# Bebidas vegetales, fórmulas y otros que el buscador del USDA mezcla con lácteos
NO_LACTEOS = re.compile(
    r"\b(RICE|SOY|ALMOND|OAT|COCONUT|CASHEW|HEMP|PEA|PLANT[- ]BASED|NON[- ]?DAIRY|DAIRY[- ]FREE|VEGAN"
    r"|INFANT FORMULA|SUPPLEMENT|BEEF|BISON|PORK|CHICKEN|CRACKERS?|COOKIES?|CANDY|CANDIES|BREAD"
    r"|BABYFOOD|BABY FOOD|TOFU|POTATO(ES)?|SHAKES?|DESSERTS?|BARS?|PUDDINGS?|ICE CREAM|FROZEN|PARFAIT"
    r"|SAUCE|SOUP|CAKES?|PIES?|PIZZA|MACARONI|SANDWICH|SNACKS?|CEREALS?|EGGNOG|SMOOTHIES?)\b"
)


def es_lacteo(row):
    return (row["tipo_producto"] != "no_especificado"
            and not NO_LACTEOS.search((row["description"] or "").upper()))


COLUMNAS = (
    ["fdc_id", "url_fuente", "description", "data_type", "brand_owner", "brand_name",
     "food_category", "market_country", "ingredients"]
    + list(KEY_NUTRIENTS.values())
    + [columna for columna, _ in REGLAS_ATRIBUTOS]
    + ["subtipo"]
)


def url_fuente(fdc_id):
    """Ficha original del alimento en la web del USDA."""
    return f"https://fdc.nal.usda.gov/food-details/{fdc_id}/nutrients"


def parse_food(food):
    row = {
        "fdc_id": food.get("fdcId"),
        "description": food.get("description"),
        "data_type": food.get("dataType"),
        "brand_owner": food.get("brandOwner"),
        "brand_name": food.get("brandName"),
        "food_category": food.get("foodCategory"),
        "market_country": food.get("marketCountry"),
        "ingredients": food.get("ingredients"),
    }
    row["url_fuente"] = url_fuente(row["fdc_id"])
    for nutrient in food.get("foodNutrients", []) or []:
        numero = str(nutrient.get("nutrientNumber") or "")
        if numero in KEY_NUTRIENTS:
            row[KEY_NUTRIENTS[numero]] = nutrient.get("value")
    row.update(atributos_producto(row["description"], row["ingredients"]))
    return row


class LimiteAlcanzado(Exception):
    pass


def fetch_usda(query, api_key, page_size=50):
    params = {
        "api_key": api_key,
        "query": query,
        "pageSize": page_size,
        "dataType": ["Foundation", "SR Legacy", "Branded"],
    }
    try:
        resp = requests.get(USDA_SEARCH_URL, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        if getattr(exc.response, "status_code", None) == 429:
            raise LimiteAlcanzado from exc
        print(f"  [aviso] falló la solicitud para {query!r}: {exc}")
        return []

    data = resp.json()
    return [parse_food(f) for f in data.get("foods", [])]


def fetch_all(queries, api_key, page_size=50):
    seen = {}
    for q in queries:
        print(f"  Buscando en USDA FoodData Central: {q!r}")
        try:
            rows = fetch_usda(q, api_key, page_size)
        except LimiteAlcanzado:
            print("  [aviso] el USDA rechazó la solicitud por límite de uso (429). "
                  "Con DEMO_KEY son 30 solicitudes por hora: consigue una key gratis en "
                  "https://fdc.nal.usda.gov/api-key-signup y ponla en USDA_API_KEY (config.py).")
            break
        for row in rows:
            if es_lacteo(row):
                seen[row["fdc_id"]] = row
        time.sleep(0.3)
    return list(seen.values())
