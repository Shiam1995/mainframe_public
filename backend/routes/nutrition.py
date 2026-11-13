"""/api/pulse/nutrition — the Nutrition area of Pulse (NUTRITION_SPEC).

Eight areas: dashboard, food log, my foods, recipes, water, weight & body,
fasting, goals. Owned by the Pulse module; every mutation hits the shared
activity log.

Two rules from the spec shape everything here:

  * **The food database starts EMPTY and is never pre-populated.** It grows only
    from foods you actually eat, which is what makes search fast and the data
    trustworthy. (An earlier build seeded ~76 generic foods; the seeder is gone.)
  * **Nutrition is stated PER SERVING**, not per 100g. A serving is whatever you
    actually eat — a slice, a scoop, 150g — so logging is "two of those" rather
    than arithmetic.

A log entry **snapshots** the macros it was created with. Correcting a food's
data later must not silently rewrite what you ate last month — the same reason
Vault snapshots transactions and Synapse snapshots paper titles.

Intolerances and supplements predate this spec and are kept; the spec neither
lists nor forbids them, and there was no reason to delete working features.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from activity import record
from db import run_read, run_write
from models import (
    BodyMeasurementCreate, BulkPasteRequest, CatalogAdopt, CopyMealsRequest, FastingEnd,
    FastingStart, FoodCreate, FoodEntryCreate, FoodEntryUpdate, FoodUpdate, IntoleranceCreate,
    NutritionGoalsUpdate, RecipeCreate, RecipeUpdate, SupplementCreate, WaterCreate,
    WeightCreate,
)

router = APIRouter(prefix="/api/pulse/nutrition", tags=["nutrition"])

MACRO_KEYS = ["calories", "protein", "carbs", "fat"]
EXTRA_KEYS = ["fibre", "sugar", "sodium"]

GOALS_ID = "nutrition-goals"          # singleton
DEFAULT_GOALS = {
    "id": GOALS_ID, "daily_calories": 2200, "protein_g": 160, "carbs_g": 250,
    "fat_g": 73, "fibre_g": 30, "water_ml": 3000, "weight_target": None,
    "weight_goal": "maintain", "fasting_protocol": "", "macro_mode": "grams",
    "height_cm": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return date.today().isoformat()


def _own(var: str) -> str:
    return f"MERGE (mod:Module {{name: 'pulse'}}) MERGE ({var})-[:OWNED_BY]->(mod)"


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _fmt_g(n: float) -> str:
    """150.0 -> '150'. Serving labels should read the way you'd say them."""
    return str(int(n)) if float(n).is_integer() else f"{n:g}"


# --------------------------------------------------------------------------- #
# Goals — the targets everything else is measured against
# --------------------------------------------------------------------------- #
async def _goals() -> dict:
    rows = await run_read("MATCH (g:NutritionGoals {id:$id}) RETURN g{.*} AS g", id=GOALS_ID)
    if rows:
        return {**DEFAULT_GOALS, **rows[0]["g"]}
    return dict(DEFAULT_GOALS)


@router.get("/goals")
async def get_goals() -> dict:
    return await _goals()


@router.put("/goals")
async def update_goals(body: NutritionGoalsUpdate) -> dict:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return await _goals()
    cur = await _goals()
    merged = {**cur, **fields, "id": GOALS_ID}
    keys = ", ".join(f"g.{k} = ${k}" for k in merged if k != "id")
    await run_write(
        f"MERGE (g:NutritionGoals {{id:$id}}) SET {keys} WITH g {_own('g')}", **merged
    )
    await record("nutrition", "goals updated", detail=", ".join(fields), module="pulse")
    return await _goals()


# --------------------------------------------------------------------------- #
# My Foods — your personal library. Starts empty; never seeded.
# --------------------------------------------------------------------------- #
@router.get("/foods")
async def list_foods(q: str | None = None, category: str | None = None,
                     limit: int = 200) -> list[dict]:
    """Most-used first — repeat logging is the common case, so it must be fastest."""
    where = []
    params: dict = {"limit": max(1, min(limit, 500))}
    if q:
        where.append("(toLower(f.name) CONTAINS toLower($q) "
                     "OR toLower(coalesce(f.brand,'')) CONTAINS toLower($q))")
        params["q"] = q
    if category:
        where.append("coalesce(f.category,'other') = $category")
        params["category"] = category
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = await run_read(
        f"""
        MATCH (f:Food) {clause}
        RETURN f{{.*}} AS f
        ORDER BY coalesce(f.favourite,false) DESC, coalesce(f.use_count,0) DESC, f.name
        LIMIT $limit
        """,
        **params,
    )
    return [r["f"] for r in rows]


@router.post("/foods", status_code=201)
async def create_food(body: FoodCreate) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "a food needs a name")
    props = {k: v for k, v in body.model_dump().items() if v is not None}
    props.update({"id": str(uuid.uuid4()), "name": body.name.strip(),
                  "use_count": 0, "favourite": False, "created_at": _now()})
    keys = ", ".join(f"{k}: ${k}" for k in props)
    rows = await run_write(
        f"CREATE (f:Food {{{keys}}}) WITH f {_own('f')} RETURN f{{.*}} AS f", **props
    )
    await record("nutrition", "food created", detail=body.name[:60], module="pulse")
    return rows[0]["f"]


@router.put("/foods/{fid}")
async def update_food(fid: str, body: FoodUpdate) -> dict:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"f.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (f:Food {{id:$id}}) SET {sets} RETURN f{{.*}} AS f", id=fid, **fields
    )
    if not rows:
        raise HTTPException(404, "food not found")
    await record("nutrition", "food updated", detail=", ".join(fields), module="pulse")
    return rows[0]["f"]


@router.delete("/foods/{fid}", status_code=204, response_class=Response)
async def delete_food(fid: str) -> Response:
    """Entries already logged keep their snapshot — deleting a food must not
    rewrite what you ate."""
    await run_write("MATCH (f:Food {id:$id}) DETACH DELETE f", id=fid)
    await record("nutrition", "food deleted", detail=fid, module="pulse")
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Food catalogue — the permanent USDA reference table (see foodcatalog.py)
#
# This is the answer to "my library starts empty, so I have to type everything".
# `:CatalogFood` is read-only reference data, kept SEPARATE from `:Food` so the
# personal library stays personal. You search it, pick a portion, and adopting
# copies a per-serving snapshot into your own library.
# --------------------------------------------------------------------------- #
CATALOG_FIELDS = [
    "fdc_id", "name", "source", "category", "portions_json", "brand", "barcode",
    "calories", "protein", "carbs", "fat", "fibre", "sugar", "saturated_fat",
    "cholesterol", "sodium", "potassium", "calcium", "iron", "magnesium",
    "zinc", "vitamin_c", "vitamin_a", "vitamin_d", "vitamin_b12", "folate",
]
# Which of those the personal `:Food` model actually understands. Anything else
# (magnesium, B12…) is carried too — FoodCreate is extra="allow" — but these are
# the ones the UI already knows how to show.
SOURCE_LABELS = {"sr_legacy": "SR Legacy", "foundation": "Foundation", "survey": "FNDDS",
                 "branded": "Branded", "off": "Open Food Facts", "cofid": "UK CoFID"}
# Fields that are text, not per-100g numbers — they must never be scaled by the
# serving-size factor when a food is adopted.
CATALOG_TEXT_FIELDS = {"fdc_id", "name", "source", "category", "portions_json", "brand", "barcode"}

# USDA's own category vocabulary → the app's. Checked in order, first hit wins,
# so "Sausages and Luncheon Meats" reaches protein before anything else claims
# it. Falls back to reading the food's name, which is all FNDDS's finer-grained
# WWEIA categories ("Milk, whole") really give us.
_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("dairy",          ("dairy and egg", "cheese", "milk", "yogurt", "yoghurt", "cream")),
    ("oils_fats",      ("fats and oils", " oil", "butter", "margarine", "lard")),
    ("protein",        ("poultry", "beef", "pork", "lamb", "sausage", "luncheon", "finfish",
                        "shellfish", "legume", "egg", "chicken", "turkey", "fish", "meat",
                        "bean", "lentil", "tofu")),
    ("nuts_seeds",     ("nut and seed", "nut ", "seed", "peanut", "almond")),
    # USDA names a category "Bananas", not "Fruit", so naming the fruits is the
    # only thing that works. Not exhaustive, and doesn't need to be — the
    # category is editable, this just beats dumping everything in "Other".
    ("fruit",          ("fruit", "berries", "berry", "juice", "banana", "apple", "orange",
                        "grape", "melon", "peach", "pear", "pineapple", "mango", "citrus",
                        "plum", "cherry", "kiwi", "apricot", "avocado", "date", "fig")),
    ("vegetables",     ("vegetable", "salad", "potato", "carrot", "broccoli", "spinach",
                        "lettuce", "tomato", "onion", "pepper", "cabbage", "cauliflower",
                        "cucumber", "courgette", "zucchini", "mushroom", "squash")),
    ("grains",         ("cereal grain", "pasta", "breakfast cereal", "rice", "oat", "grain")),
    ("bread_bakery",   ("baked product", "bread", "cake", "pastry", "biscuit", "cookie")),
    ("drinks",         ("beverage", "drink", "coffee", "tea", "soft drink", "water")),
    ("snacks",         ("sweets", "snack", "candy", "chocolate", "crisps", "chips", "dessert")),
    ("condiments",     ("spices and herbs", "soups, sauces", "sauce", "dressing", "condiment",
                        "syrup", "spice")),
    ("prepared_meals", ("fast food", "meals, entrees", "restaurant", "pizza", "sandwich",
                        "soup", "stew")),
]


def _app_category(usda_category: str, name: str) -> str:
    """Best-effort bucket for an adopted food. Wrong-but-editable beats 'Other'
    for everything, which is what raw USDA category strings would give."""
    hay = f"{usda_category} {name}".lower()
    for key, needles in _CATEGORY_RULES:
        if any(nd in hay for nd in needles):
            return key
    return "other"


def _catalog_out(c: dict) -> dict:
    out = {k: c.get(k) for k in CATALOG_FIELDS if c.get(k) is not None}
    out["portions"] = json.loads(c.get("portions_json") or "[]")
    out.pop("portions_json", None)
    out["source_label"] = SOURCE_LABELS.get(c.get("source", ""), c.get("source", ""))
    return out


def _search_words(q: str) -> list[str]:
    """Reduce a typed query to plain words.

    Anything not alphanumeric becomes a space. That's blunt on purpose: a food
    search is full of commas, percent signs and brackets ("milk, 2%"), and every
    one of them is either a Lucene operator or punctuation Lucene already
    stripped when it indexed the name. Keeping them produced `milk,* AND 2%*`,
    which matches nothing at all — the bug this replaced.
    """
    return [w for w in re.sub(r"[^0-9a-zA-Z]+", " ", q).split() if w]


# Whole foods outrank packaged ones. With ~1.9M branded USDA rows and ~2.2M
# Open Food Facts products against ~13.6k reference foods, a plain search for
# "banana" would otherwise return several hundred branded snack bars before the
# actual fruit. Grouping first and scoring within the group fixes that while
# still finding "hobnobs", which only exists as a branded product.
_RANK_CASE = """
CASE c.source
  WHEN 'foundation' THEN 0 WHEN 'sr_legacy' THEN 0 WHEN 'survey' THEN 0
  ELSE 1 END
"""


@router.get("/catalog")
async def search_catalog(q: str = "", source: str | None = None, limit: int = 40) -> list[dict]:
    """Search the reference catalogue. Full-text first, CONTAINS as a fallback."""
    lim = max(1, min(limit, 200))
    q = (q or "").strip()
    if not q:
        return []

    # A long run of digits is a barcode, not a name — go straight at it.
    digits = re.sub(r"[^0-9]", "", q)
    if len(digits) >= 8 and len(digits) == len(q.replace(" ", "")):
        rows = await _catalog_by_barcode(digits, lim)
        if rows:
            return rows

    words = _search_words(q)
    if not words:
        return []
    # Every word required, each as a prefix — so "chick brea" narrows to chicken
    # breast instead of returning everything matching either word.
    lucene = " AND ".join(f"{w}*" for w in words)
    rows: list[dict] = []
    if lucene:
        try:
            rows = await run_read(
                f"""
                CALL db.index.fulltext.queryNodes('catalogfood_search_text', $lucene,
                                                  {{limit: $scan}})
                YIELD node AS c, score
                WHERE $source IS NULL OR c.source = $source
                WITH c, score, {_RANK_CASE} AS grp
                RETURN c{{.*}} AS c, score
                ORDER BY grp ASC, score DESC, size(c.name) ASC
                LIMIT $limit
                """,
                # Take the most relevant N from the index, THEN re-rank them.
                # Without the cap, a common word like "chicken" makes the
                # procedure stream every one of its ~100k matches before the
                # sort can start. A wider net when a source filter is set,
                # since most candidates will be filtered out.
                lucene=lucene, source=source, limit=lim,
                scan=2000 if source else 400,
            )
        except Exception:      # index missing or query rejected — fall through
            rows = []
    if not rows:
        # Fallback: every word must appear somewhere in the name. Matching the
        # raw typed string would fail on "milk, 2%", because no name contains
        # those characters in that order.
        rows = await run_read(
            """
            MATCH (c:CatalogFood)
            WHERE ($source IS NULL OR c.source = $source)
              AND all(w IN $words WHERE c.search_name CONTAINS w)
            RETURN c{.*} AS c, 0.0 AS score
            ORDER BY size(c.name) ASC
            LIMIT $limit
            """,
            words=[w.lower() for w in words], source=source, limit=lim,
        )
    return [_catalog_out(r["c"]) for r in rows]


@router.get("/catalog/status")
async def catalog_status() -> dict:
    """What's imported, and what archives are sitting on disk to import from."""
    import foodcatalog
    return await foodcatalog.status()


@router.post("/catalog/import")
async def catalog_import(source: str | None = None) -> dict:
    """Re-run the import. Idempotent — MERGEs on fdc_id, so it repairs rather
    than duplicates. Needs no network: it reads the archives already on disk.

    `?source=` limits it to one source. Worth using: a full import of every
    source is ~4 million rows and takes about a quarter of an hour, which is far
    longer than anything should hold an HTTP request open. For a full rebuild,
    run `python foodcatalog.py` instead.
    """
    import foodcatalog
    try:
        summary = await foodcatalog.import_all(only=source)
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    await record("nutrition", "food catalogue imported",
                 detail=f"{summary['total']} foods", module="pulse", trigger="system")
    return summary


async def _catalog_by_barcode(code: str, limit: int = 20) -> list[dict]:
    """Find a product by barcode, trying every legal spelling of the code.

    The same GTIN lives in the catalogue as 12, 13 or 14 digits depending on
    which source imported it (see barcodescan.variants), so a single exact match
    misses products that are demonstrably there.
    """
    import barcodescan
    codes = barcodescan.variants(code)
    if not codes:
        return []
    rows = await run_read(
        "MATCH (c:CatalogFood) WHERE c.barcode IN $codes RETURN c{.*} AS c LIMIT $limit",
        codes=codes, limit=limit,
    )
    order = {v: i for i, v in enumerate(codes)}
    out = [_catalog_out(r["c"]) for r in rows]
    # Closest spelling first: the code as scanned beats a zero-padded guess.
    out.sort(key=lambda f: order.get(f.get("barcode", ""), len(order)))
    return out


@router.post("/catalog/scan")
async def scan_catalog(image: UploadFile = File(...), limit: int = 12) -> dict:
    """Photograph a barcode; get the product back.

    The catalogue holds ~4M products carrying a barcode, so the packet in your
    hand can identify itself instead of being typed in. Decoding is local
    (zxing-cpp) and the image is held in memory only — it is never stored.

    A frame with no barcode in it is a normal answer, not an error: a live
    camera sends many frames and most of them are blurred.
    """
    import barcodescan
    if not barcodescan.available():
        raise HTTPException(503, "the barcode decoder isn't installed — pip install zxing-cpp")

    data = await image.read()
    if not data:
        raise HTTPException(400, "empty image")
    if len(data) > 16_000_000:
        raise HTTPException(413, "image too large — 16 MB is plenty for a barcode")

    # Decoding is CPU work in C++; keep it off the event loop so a camera loop
    # can't stall every other request in the app.
    try:
        codes = await asyncio.to_thread(barcodescan.decode, data)
    except Exception as exc:                       # not an image, truncated upload…
        raise HTTPException(400, f"could not read that image: {exc}") from exc

    lim = max(1, min(limit, 50))
    matches: list[dict] = []
    seen: set[str] = set()
    for c in codes:
        found = await _catalog_by_barcode(c["code"], lim)
        c["matched"] = len(found)
        for f in found:
            if f["fdc_id"] in seen:
                continue
            seen.add(f["fdc_id"])
            f["scanned_code"] = c["code"]
            matches.append(f)
    return {"codes": codes, "matches": matches[:lim]}


@router.get("/catalog/{fdc_id}")
async def get_catalog_food(fdc_id: str) -> dict:
    rows = await run_read("MATCH (c:CatalogFood {fdc_id:$id}) RETURN c{.*} AS c", id=fdc_id)
    if not rows:
        raise HTTPException(404, "not in the catalogue")
    return _catalog_out(rows[0]["c"])


@router.post("/catalog/{fdc_id}/adopt", status_code=201)
async def adopt_catalog_food(fdc_id: str, body: CatalogAdopt) -> dict:
    """Copy a catalogue entry into your personal library, converted to a serving.

    USDA states everything per 100 g; the spec states food per serving. This is
    where the two meet, and it is the ONLY place the conversion happens.

    The copy is a **snapshot**, not a link. Re-importing USDA data later must not
    silently change a food you have been logging for months — the same rule the
    log entries themselves follow.
    """
    rows = await run_read("MATCH (c:CatalogFood {fdc_id:$id}) RETURN c{.*} AS c", id=fdc_id)
    if not rows:
        raise HTTPException(404, "not in the catalogue")
    c = rows[0]["c"]

    grams = _num(body.serving_g, 0)
    if grams <= 0:
        raise HTTPException(400, "a serving needs a gram weight")
    factor = grams / 100.0

    props: dict = {
        "id": str(uuid.uuid4()),
        "name": (body.name or c["name"]).strip(),
        "brand": c.get("brand") or "",
        "barcode": c.get("barcode") or "",
        "category": _app_category(c.get("category") or "", c.get("name") or ""),
        "usda_category": c.get("category") or "",   # keep what the source actually said
        "serving_size": round(grams, 2),
        "serving_unit": "g",
        "serving_label": (body.serving_label or f"{_fmt_g(grams)} g").strip(),
        "use_count": 0,
        "favourite": False,
        # "verified" means measured by someone, not typed in by you. Open Food
        # Facts is crowd-sourced, so it does NOT get the badge — the distinction
        # is the whole value of the flag.
        "verified": c.get("source") != "off",
        "source": c.get("source") or "catalogue",   # which table it actually came from
        "source_label": SOURCE_LABELS.get(c.get("source", ""), ""),
        "fdc_id": c["fdc_id"],          # provenance, not a live link
        "created_at": _now(),
    }
    for key in CATALOG_FIELDS:
        if key in CATALOG_TEXT_FIELDS:
            continue
        val = c.get(key)
        if val is not None:
            props[key] = round(float(val) * factor, 3)

    keys = ", ".join(f"{k}: ${k}" for k in props)
    created = await run_write(
        f"CREATE (f:Food {{{keys}}}) WITH f {_own('f')} RETURN f{{.*}} AS f", **props
    )
    await record("nutrition", "food added from catalogue",
                 detail=f"{props['name'][:50]} · {props['serving_label']}", module="pulse")
    return created[0]["f"]


# --------------------------------------------------------------------------- #
# Food log
# --------------------------------------------------------------------------- #
async def _bump_use(food_id: str | None) -> None:
    if food_id:
        await run_write(
            "MATCH (f:Food {id:$id}) SET f.use_count = coalesce(f.use_count,0) + 1", id=food_id
        )


async def _create_entry(data: dict) -> dict:
    props = {k: v for k, v in data.items() if v is not None}
    props.setdefault("date", _today())
    props.update({"id": str(uuid.uuid4()), "created_at": _now()})
    food_id = props.pop("food_id", None)
    keys = ", ".join(f"{k}: ${k}" for k in props)
    rows = await run_write(
        f"CREATE (e:FoodEntry {{{keys}}}) WITH e {_own('e')} RETURN e{{.*}} AS e", **props
    )
    entry = rows[0]["e"]
    if food_id:
        await run_write(
            "MATCH (e:FoodEntry {id:$eid}), (f:Food {id:$fid}) MERGE (e)-[:USES_FOOD]->(f)",
            eid=entry["id"], fid=food_id,
        )
        await _bump_use(food_id)
        entry["food_id"] = food_id
    return entry


@router.get("/log")
async def list_log(date_: str | None = None) -> dict:
    """A day's entries, grouped by meal slot with per-slot totals."""
    d = date_ or _today()
    rows = await run_read(
        """
        MATCH (e:FoodEntry {date:$d})
        OPTIONAL MATCH (e)-[:USES_FOOD]->(f:Food)
        RETURN e{.*} AS e, f.id AS food_id
        ORDER BY coalesce(e.time,''), e.created_at
        """,
        d=d,
    )
    entries = []
    for r in rows:
        e = r["e"]
        e["food_id"] = r["food_id"]
        entries.append(e)
    slots: dict[str, dict] = {}
    for e in entries:
        s = e.get("meal_slot") or "snacks"
        slot = slots.setdefault(s, {"meal_slot": s, "entries": [], **{k: 0.0 for k in MACRO_KEYS}})
        slot["entries"].append(e)
        for k in MACRO_KEYS:
            slot[k] += _num(e.get(k))
    totals = {k: round(sum(_num(e.get(k)) for e in entries), 1) for k in MACRO_KEYS}
    for k in EXTRA_KEYS:
        totals[k] = round(sum(_num(e.get(k)) for e in entries), 1)
    return {"date": d, "entries": entries, "slots": list(slots.values()), "totals": totals}


@router.post("/log", status_code=201)
async def add_entry(body: FoodEntryCreate) -> dict:
    entry = await _create_entry(body.model_dump())
    await record("nutrition", "food logged",
                 detail=f"{entry.get('food_name','')[:40]} · {int(_num(entry.get('calories')))} cal",
                 module="pulse")
    return entry


@router.post("/log/quick", status_code=201)
async def quick_add(body: FoodEntryCreate) -> dict:
    """Calories + macros with no food behind them. The fastest possible log."""
    data = body.model_dump()
    data["food_name"] = (body.food_name or "Quick add").strip() or "Quick add"
    data["food_id"] = None
    entry = await _create_entry(data)
    await record("nutrition", "quick add", detail=f"{int(_num(entry.get('calories')))} cal", module="pulse")
    return entry


_NUM_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def _parse_bulk_line(line: str) -> dict | None:
    """`Chicken breast, 150g, 248 cal, 46g protein, 0g carbs, 5g fat` → an entry.

    Deliberately forgiving about order and wording: each field is found by the
    unit word next to a number, so `protein 46g` and `46g protein` both work.
    A line with no calories AND no macros isn't food, and is reported, not
    silently dropped.
    """
    raw = line.strip().strip("-•*").strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",")]
    name = parts[0] if parts else raw
    out = {"food_name": name, "serving_size": 1, "serving_unit": "serving"}
    found = False
    for p in parts[1:] + ([] if len(parts) > 1 else [raw]):
        low = p.lower()
        m = _NUM_RE.search(p)
        if not m:
            continue
        val = float(m.group(1))
        if "protein" in low:
            out["protein"] = val; found = True
        elif "carb" in low:
            out["carbs"] = val; found = True
        elif "fat" in low:
            out["fat"] = val; found = True
        elif "fibre" in low or "fiber" in low:
            out["fibre"] = val
        elif "sugar" in low:
            out["sugar"] = val
        elif "cal" in low or "kcal" in low:
            out["calories"] = val; found = True
        elif re.search(r"\d\s*(g|ml|kg)\b", low):
            out["serving_size"] = val
            out["serving_unit"] = "ml" if "ml" in low else "g"
    return out if found else None


@router.post("/log/bulk")
async def bulk_paste(body: BulkPasteRequest) -> dict:
    """Paste a list of foods. `dry_run` returns the preview without writing —
    the same mandatory-preview rule Vault's bulk paste follows."""
    lines = [ln for ln in (body.text or "").splitlines() if ln.strip()]
    parsed, rejected = [], []
    for i, ln in enumerate(lines, 1):
        row = _parse_bulk_line(ln)
        if row:
            row["date"] = body.date or _today()
            row["meal_slot"] = body.meal_slot
            parsed.append(row)
        else:
            rejected.append({"line": i, "text": ln.strip(),
                             "why": "no calories or macros found on this line"})
    if body.dry_run:
        return {"parsed": parsed, "rejected": rejected,
                "counts": {"ok": len(parsed), "rejected": len(rejected)}}
    created = [await _create_entry(dict(r)) for r in parsed]
    await record("nutrition", "bulk paste", detail=f"{len(created)} entries", module="pulse")
    return {"created": created, "rejected": rejected,
            "counts": {"ok": len(created), "rejected": len(rejected)}}


@router.put("/log/{eid}")
async def update_entry(eid: str, body: FoodEntryUpdate) -> dict:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"e.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (e:FoodEntry {{id:$id}}) SET {sets} RETURN e{{.*}} AS e", id=eid, **fields
    )
    if not rows:
        raise HTTPException(404, "entry not found")
    await record("nutrition", "food entry updated", detail=", ".join(fields), module="pulse")
    return rows[0]["e"]


@router.delete("/log/{eid}", status_code=204, response_class=Response)
async def delete_entry(eid: str) -> Response:
    await run_write("MATCH (e:FoodEntry {id:$id}) DETACH DELETE e", id=eid)
    await record("nutrition", "food entry deleted", detail=eid, module="pulse")
    return Response(status_code=204)


@router.post("/log/copy")
async def copy_meals(body: CopyMealsRequest) -> dict:
    """Copy a past day, or one meal from it, onto another day. You eat the same
    breakfast repeatedly — that should be one click, not re-entry."""
    to = body.to_date or _today()
    where = "e.date = $from"
    params: dict = {"from": body.from_date}
    if body.meal_slot:
        where += " AND e.meal_slot = $slot"
        params["slot"] = body.meal_slot
    rows = await run_read(
        f"""
        MATCH (e:FoodEntry) WHERE {where}
        OPTIONAL MATCH (e)-[:USES_FOOD]->(f:Food)
        RETURN e{{.*}} AS e, f.id AS food_id
        """,
        **params,
    )
    made = []
    for r in rows:
        src = dict(r["e"])
        for drop in ("id", "created_at"):
            src.pop(drop, None)
        src["date"] = to
        src["food_id"] = r["food_id"]
        made.append(await _create_entry(src))
    await record("nutrition", "meals copied",
                 detail=f"{len(made)} from {body.from_date} → {to}", module="pulse")
    return {"created": len(made), "entries": made, "date": to}


# --------------------------------------------------------------------------- #
# Recipes
# --------------------------------------------------------------------------- #
def _recipe_totals(ingredients: list[dict], servings: int) -> dict:
    total = {k: round(sum(_num(i.get(k)) for i in ingredients), 1) for k in MACRO_KEYS}
    n = max(1, int(servings or 1))
    per = {k: round(total[k] / n, 1) for k in MACRO_KEYS}
    return {"total": total, "per_serving": per}


def _recipe_out(node: dict) -> dict:
    r = dict(node)
    try:
        r["ingredients"] = json.loads(r.get("ingredients_json") or "[]")
    except (ValueError, TypeError):
        r["ingredients"] = []
    r.pop("ingredients_json", None)
    calc = _recipe_totals(r["ingredients"], r.get("servings") or 1)
    r["totals"] = calc["total"]
    r["per_serving"] = calc["per_serving"]
    return r


@router.get("/recipes")
async def list_recipes() -> list[dict]:
    rows = await run_read(
        "MATCH (r:Recipe) RETURN r{.*} AS r "
        "ORDER BY coalesce(r.use_count,0) DESC, r.name"
    )
    return [_recipe_out(r["r"]) for r in rows]


async def _link_ingredients(rid: str, ingredients: list[dict]) -> None:
    """Draw CONTAINS edges for ingredients that are library foods. Ad-hoc
    ingredients (typed, not picked) live only in the JSON — the recipe must not
    demand that everything in it already exists as a Food."""
    await run_write("MATCH (:Recipe {id:$id})-[c:CONTAINS]->() DELETE c", id=rid)
    for ing in ingredients:
        if ing.get("food_id"):
            await run_write(
                "MATCH (r:Recipe {id:$rid}), (f:Food {id:$fid}) "
                "MERGE (r)-[c:CONTAINS]->(f) "
                "SET c.serving_size = $ss, c.serving_unit = $su",
                rid=rid, fid=ing["food_id"], ss=_num(ing.get("serving_size"), 1),
                su=ing.get("serving_unit") or "serving",
            )


@router.post("/recipes", status_code=201)
async def create_recipe(body: RecipeCreate) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "a recipe needs a name")
    rid = str(uuid.uuid4())
    ings = [i.model_dump() for i in body.ingredients]
    calc = _recipe_totals(ings, body.servings)
    rows = await run_write(
        f"""
        CREATE (r:Recipe {{
            id:$id, name:$name, servings:$servings, ingredients_json:$ings,
            instructions:$instructions, prep_time:$prep, cook_time:$cook,
            category:$category, use_count:0,
            total_calories:$tc, total_protein:$tp, total_carbs:$tcarb, total_fat:$tf,
            created_at:$now
        }}) WITH r {_own('r')} RETURN r{{.*}} AS r
        """,
        id=rid, name=body.name.strip(), servings=max(1, body.servings),
        ings=json.dumps(ings), instructions=body.instructions,
        prep=body.prep_time, cook=body.cook_time, category=body.category,
        tc=calc["total"]["calories"], tp=calc["total"]["protein"],
        tcarb=calc["total"]["carbs"], tf=calc["total"]["fat"], now=_now(),
    )
    await _link_ingredients(rid, ings)
    await record("nutrition", "recipe created", detail=body.name[:60], module="pulse")
    return _recipe_out(rows[0]["r"])


@router.put("/recipes/{rid}")
async def update_recipe(rid: str, body: RecipeUpdate) -> dict:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    ings = None
    if "ingredients" in fields:
        ings = [i if isinstance(i, dict) else i.model_dump() for i in (fields.pop("ingredients") or [])]
        fields["ingredients_json"] = json.dumps(ings)
    cur = await run_read("MATCH (r:Recipe {id:$id}) RETURN r{.*} AS r", id=rid)
    if not cur:
        raise HTTPException(404, "recipe not found")
    existing = _recipe_out(cur[0]["r"])
    calc = _recipe_totals(ings if ings is not None else existing["ingredients"],
                          fields.get("servings", existing.get("servings") or 1))
    fields.update({"total_calories": calc["total"]["calories"],
                   "total_protein": calc["total"]["protein"],
                   "total_carbs": calc["total"]["carbs"],
                   "total_fat": calc["total"]["fat"]})
    sets = ", ".join(f"r.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (r:Recipe {{id:$id}}) SET {sets} RETURN r{{.*}} AS r", id=rid, **fields
    )
    if ings is not None:
        await _link_ingredients(rid, ings)
    await record("nutrition", "recipe updated", detail=", ".join(fields), module="pulse")
    return _recipe_out(rows[0]["r"])


@router.delete("/recipes/{rid}", status_code=204, response_class=Response)
async def delete_recipe(rid: str) -> Response:
    await run_write("MATCH (r:Recipe {id:$id}) DETACH DELETE r", id=rid)
    await record("nutrition", "recipe deleted", detail=rid, module="pulse")
    return Response(status_code=204)


@router.post("/recipes/{rid}/log", status_code=201)
async def log_recipe(rid: str, servings: float = 1, meal_slot: str = "dinner",
                     date_: str | None = None) -> dict:
    """One serving (or several) of a recipe onto a day, as a single entry."""
    rows = await run_read("MATCH (r:Recipe {id:$id}) RETURN r{.*} AS r", id=rid)
    if not rows:
        raise HTTPException(404, "recipe not found")
    r = _recipe_out(rows[0]["r"])
    per = r["per_serving"]
    entry = await _create_entry({
        "date": date_ or _today(), "meal_slot": meal_slot,
        "food_name": r["name"], "serving_size": servings, "serving_unit": "serving",
        **{k: round(per[k] * servings, 1) for k in MACRO_KEYS},
        "notes": "from recipe",
    })
    await run_write("MATCH (r:Recipe {id:$id}) SET r.use_count = coalesce(r.use_count,0)+1", id=rid)
    await record("nutrition", "recipe logged", detail=r["name"][:60], module="pulse")
    return entry


# --------------------------------------------------------------------------- #
# Water
# --------------------------------------------------------------------------- #
@router.get("/water")
async def list_water(date_: str | None = None) -> dict:
    d = date_ or _today()
    rows = await run_read(
        "MATCH (w:WaterEntry {date:$d}) RETURN w{.*} AS w ORDER BY coalesce(w.time,''), w.created_at",
        d=d,
    )
    entries = [r["w"] for r in rows]
    goals = await _goals()
    total = round(sum(_num(e.get("amount")) for e in entries))
    return {"date": d, "entries": entries, "total_ml": total,
            "target_ml": goals.get("water_ml") or 3000}


@router.post("/water", status_code=201)
async def add_water(body: WaterCreate) -> dict:
    wid = str(uuid.uuid4())
    rows = await run_write(
        f"""CREATE (w:WaterEntry {{id:$id, date:$date, amount:$amount, time:$time,
            created_at:$now}}) WITH w {_own('w')} RETURN w{{.*}} AS w""",
        id=wid, date=body.date or _today(), amount=_num(body.amount), time=body.time, now=_now(),
    )
    await record("nutrition", "water logged", detail=f"{int(_num(body.amount))}ml", module="pulse")
    return rows[0]["w"]


@router.delete("/water/{wid}", status_code=204, response_class=Response)
async def delete_water(wid: str) -> Response:
    await run_write("MATCH (w:WaterEntry {id:$id}) DETACH DELETE w", id=wid)
    await record("nutrition", "water entry deleted", detail=wid, module="pulse")
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Weight & body
# --------------------------------------------------------------------------- #
@router.get("/weight")
async def list_weight() -> list[dict]:
    rows = await run_read("MATCH (w:WeightEntry) RETURN w{.*} AS w ORDER BY w.date")
    return [r["w"] for r in rows]


@router.post("/weight", status_code=201)
async def add_weight(body: WeightCreate) -> dict:
    wid = str(uuid.uuid4())
    rows = await run_write(
        f"""CREATE (w:WeightEntry {{id:$id, date:$date, weight:$weight, notes:$notes,
            created_at:$now}}) WITH w {_own('w')} RETURN w{{.*}} AS w""",
        id=wid, date=body.date or _today(), weight=_num(body.weight), notes=body.notes, now=_now(),
    )
    await record("nutrition", "weight logged", detail=f"{body.weight}kg", module="pulse")
    return rows[0]["w"]


@router.delete("/weight/{wid}", status_code=204, response_class=Response)
async def delete_weight(wid: str) -> Response:
    await run_write("MATCH (w:WeightEntry {id:$id}) DETACH DELETE w", id=wid)
    await record("nutrition", "weight entry deleted", detail=wid, module="pulse")
    return Response(status_code=204)


@router.get("/weight/trend")
async def weight_trend(days: int = 90) -> dict:
    """Daily points plus a smoothed weekly average — a daily weight bounces by a
    kilo on water alone, so the average is what actually shows the direction."""
    rows = await run_read("MATCH (w:WeightEntry) RETURN w{.*} AS w ORDER BY w.date")
    points = [{"date": r["w"]["date"], "weight": _num(r["w"].get("weight"))} for r in rows]
    cutoff = (date.today() - timedelta(days=max(1, days))).isoformat()
    points = [p for p in points if p["date"] >= cutoff]
    weekly: dict[str, list[float]] = {}
    for p in points:
        try:
            d = datetime.fromisoformat(p["date"]).date()
        except ValueError:
            continue
        monday = (d - timedelta(days=d.weekday())).isoformat()
        weekly.setdefault(monday, []).append(p["weight"])
    avg = [{"week": k, "weight": round(sum(v) / len(v), 2)} for k, v in sorted(weekly.items())]
    goals = await _goals()
    first, last = (points[0]["weight"] if points else None), (points[-1]["weight"] if points else None)
    return {
        "points": points, "weekly_average": avg,
        "start": first, "current": last,
        "change": round(last - first, 2) if (first is not None and last is not None) else None,
        "target": goals.get("weight_target"), "goal": goals.get("weight_goal"),
    }


@router.get("/body")
async def list_body() -> list[dict]:
    rows = await run_read("MATCH (b:BodyMeasurement) RETURN b{.*} AS b ORDER BY b.date DESC")
    out = []
    goals = await _goals()
    height = _num(goals.get("height_cm"), 0)
    for r in rows:
        b = dict(r["b"])
        waist = _num(b.get("waist"), 0)
        hips = _num(b.get("hips"), 0)
        # Ratios only where the inputs exist — a derived number from a missing
        # measurement is worse than no number.
        b["waist_to_height"] = round(waist / height, 3) if waist and height else None
        b["waist_to_hip"] = round(waist / hips, 3) if waist and hips else None
        out.append(b)
    return out


@router.post("/body", status_code=201)
async def add_body(body: BodyMeasurementCreate) -> dict:
    props = {k: v for k, v in body.model_dump().items() if v is not None}
    props.update({"id": str(uuid.uuid4()), "date": body.date or _today(), "created_at": _now()})
    keys = ", ".join(f"{k}: ${k}" for k in props)
    rows = await run_write(
        f"CREATE (b:BodyMeasurement {{{keys}}}) WITH b {_own('b')} RETURN b{{.*}} AS b", **props
    )
    await record("nutrition", "body measurements logged",
                 detail=", ".join(k for k in props if k not in ("id", "date", "created_at", "notes")),
                 module="pulse")
    return rows[0]["b"]


@router.delete("/body/{bid}", status_code=204, response_class=Response)
async def delete_body(bid: str) -> Response:
    await run_write("MATCH (b:BodyMeasurement {id:$id}) DETACH DELETE b", id=bid)
    await record("nutrition", "body measurement deleted", detail=bid, module="pulse")
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Fasting
# --------------------------------------------------------------------------- #
@router.get("/fasting")
async def list_fasting() -> dict:
    rows = await run_read(
        "MATCH (f:FastingSession) RETURN f{.*} AS f ORDER BY f.start_time DESC LIMIT 200"
    )
    sessions = [r["f"] for r in rows]
    active = next((s for s in sessions if not s.get("end_time")), None)
    done = [s for s in sessions if s.get("end_time")]
    avg = round(sum(_num(s.get("actual_hours")) for s in done) / len(done), 1) if done else None
    return {"sessions": sessions, "active": active,
            "completed_count": sum(1 for s in done if s.get("completed")),
            "average_hours": avg}


@router.post("/fasting/start", status_code=201)
async def start_fast(body: FastingStart) -> dict:
    open_rows = await run_read(
        "MATCH (f:FastingSession) WHERE f.end_time IS NULL RETURN f{.*} AS f LIMIT 1"
    )
    if open_rows:
        raise HTTPException(400, "a fast is already running — end it before starting another")
    fid = str(uuid.uuid4())
    rows = await run_write(
        f"""CREATE (f:FastingSession {{id:$id, start_time:$start, end_time:null,
            target_hours:$target, actual_hours:0.0, completed:false, notes:$notes,
            created_at:$now}}) WITH f {_own('f')} RETURN f{{.*}} AS f""",
        id=fid, start=body.start_time or _now(), target=_num(body.target_hours, 16),
        notes=body.notes, now=_now(),
    )
    await record("nutrition", "fasting started", detail=f"target {body.target_hours}h", module="pulse")
    return rows[0]["f"]


@router.put("/fasting/{fid}/end")
async def end_fast(fid: str, body: FastingEnd) -> dict:
    rows = await run_read("MATCH (f:FastingSession {id:$id}) RETURN f{.*} AS f", id=fid)
    if not rows:
        raise HTTPException(404, "fast not found")
    f = rows[0]["f"]
    end = body.end_time or _now()
    try:
        hours = (datetime.fromisoformat(end) - datetime.fromisoformat(f["start_time"])).total_seconds() / 3600
    except (ValueError, TypeError):
        hours = 0.0
    hours = round(max(0.0, hours), 2)
    completed = hours >= _num(f.get("target_hours"), 16)
    out = await run_write(
        "MATCH (f:FastingSession {id:$id}) SET f.end_time=$end, f.actual_hours=$h, "
        "f.completed=$c, f.notes=coalesce($notes, f.notes) RETURN f{.*} AS f",
        id=fid, end=end, h=hours, c=completed, notes=body.notes,
    )
    await record("nutrition", "fasting ended" if completed else "fasting broken",
                 detail=f"{hours}h of {f.get('target_hours')}h", module="pulse")
    return out[0]["f"]


@router.delete("/fasting/{fid}", status_code=204, response_class=Response)
async def delete_fast(fid: str) -> Response:
    await run_write("MATCH (f:FastingSession {id:$id}) DETACH DELETE f", id=fid)
    await record("nutrition", "fasting session deleted", detail=fid, module="pulse")
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@router.get("/dashboard")
async def dashboard(date_: str | None = None) -> dict:
    d = date_ or _today()
    goals = await _goals()
    log = await list_log(d)
    water = await list_water(d)
    weights = await list_weight()

    # streak — consecutive days, ending today, with at least one entry
    day_rows = await run_read(
        "MATCH (e:FoodEntry) WHERE e.date IS NOT NULL RETURN DISTINCT e.date AS d ORDER BY d DESC"
    )
    logged = {r["d"] for r in day_rows}
    streak, cursor = 0, date.fromisoformat(d)
    while cursor.isoformat() in logged:
        streak += 1
        cursor -= timedelta(days=1)

    # weekly average calories over the last 7 days that have any entry
    week_start = (date.fromisoformat(d) - timedelta(days=6)).isoformat()
    wk = await run_read(
        "MATCH (e:FoodEntry) WHERE e.date >= $s AND e.date <= $d "
        "RETURN e.date AS day, sum(coalesce(e.calories,0)) AS cal",
        s=week_start, d=d,
    )
    weekly_avg = round(sum(_num(r["cal"]) for r in wk) / len(wk)) if wk else 0

    # weight trend vs last week
    trend = None
    if len(weights) >= 2:
        latest = _num(weights[-1].get("weight"))
        cutoff = (date.fromisoformat(d) - timedelta(days=7)).isoformat()
        prior = [w for w in weights if w["date"] <= cutoff]
        if prior:
            delta = latest - _num(prior[-1].get("weight"))
            trend = {"delta": round(delta, 2),
                     "direction": "up" if delta > 0.2 else "down" if delta < -0.2 else "stable"}

    fasting = await list_fasting()
    return {
        "date": d,
        "goals": goals,
        "totals": log["totals"],
        "slots": [{"meal_slot": s["meal_slot"], **{k: round(s[k], 1) for k in MACRO_KEYS}}
                  for s in log["slots"]],
        "remaining": {
            "calories": round(_num(goals.get("daily_calories")) - _num(log["totals"].get("calories"))),
            "protein": round(_num(goals.get("protein_g")) - _num(log["totals"].get("protein"))),
            "carbs": round(_num(goals.get("carbs_g")) - _num(log["totals"].get("carbs"))),
            "fat": round(_num(goals.get("fat_g")) - _num(log["totals"].get("fat"))),
        },
        "water": {"total_ml": water["total_ml"], "target_ml": water["target_ml"]},
        "weight": {"current": _num(weights[-1].get("weight")) if weights else None, "trend": trend},
        "streak_days": streak,
        "weekly_avg_calories": weekly_avg,
        "fasting_active": fasting["active"],
        "entry_count": len(log["entries"]),
    }


# --------------------------------------------------------------------------- #
# Intolerances + Supplements (pre-date this spec; kept)
# --------------------------------------------------------------------------- #
@router.get("/intolerances")
async def list_intolerances() -> list[dict]:
    rows = await run_read("MATCH (i:Intolerance) RETURN i{.*} AS i ORDER BY i.name")
    return [r["i"] for r in rows]


@router.post("/intolerances", status_code=201)
async def add_intolerance(body: IntoleranceCreate) -> dict:
    iid = str(uuid.uuid4())
    rows = await run_write(
        f"CREATE (i:Intolerance {{id:$id, name:$name, severity:$sev, notes:$notes, created_at:$now}}) WITH i {_own('i')} RETURN i{{.*}} AS i",
        id=iid, name=body.name.strip(), sev=body.severity, notes=body.notes, now=_now(),
    )
    await record("nutrition", "intolerance added", detail=body.name[:50], module="pulse")
    return rows[0]["i"]


@router.delete("/intolerances/{iid}", status_code=204, response_class=Response)
async def del_intolerance(iid: str) -> Response:
    await run_write("MATCH (i:Intolerance {id:$id}) DETACH DELETE i", id=iid)
    await record("nutrition", "intolerance removed", detail=iid, module="pulse")
    return Response(status_code=204)


@router.get("/supplements")
async def list_supplements() -> list[dict]:
    rows = await run_read("MATCH (s:Supplement) RETURN s{.*} AS s ORDER BY s.name")
    return [r["s"] for r in rows]


@router.post("/supplements", status_code=201)
async def add_supplement(body: SupplementCreate) -> dict:
    sid = str(uuid.uuid4())
    rows = await run_write(
        f"CREATE (s:Supplement {{id:$id, name:$name, dose:$dose, timing:$timing, notes:$notes, created_at:$now}}) WITH s {_own('s')} RETURN s{{.*}} AS s",
        id=sid, name=body.name.strip(), dose=body.dose, timing=body.timing, notes=body.notes, now=_now(),
    )
    await record("nutrition", "supplement added", detail=body.name[:50], module="pulse")
    return rows[0]["s"]


@router.delete("/supplements/{sid}", status_code=204, response_class=Response)
async def del_supplement(sid: str) -> Response:
    await run_write("MATCH (s:Supplement {id:$id}) DETACH DELETE s", id=sid)
    await record("nutrition", "supplement removed", detail=sid, module="pulse")
    return Response(status_code=204)
