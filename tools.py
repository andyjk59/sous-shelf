"""The tools the harness can run, and the JSON that describes them to the model.

Every tool returns a plain dict. On failure it returns {"error": ..., "suggestion": ...}
so the model can recover or tell the user what to do.
"""

import difflib
import json
import math
import os
import re
import time
from functools import lru_cache

import requests
from dotenv import load_dotenv

from pantry_rules import (
    ALIASES,
    COOKING_OILS,
    DEFAULT_MAX_ADDED_FAT_G,
    DEFAULT_PANTRY,
    DEFAULT_PROTEIN_G_PER_SERVING,
    DEFAULT_VEGETABLE_G_PER_SERVING,
    FAT_G_PER_TSP,
    FLAVOR_BASES,
    FLAVOR_NOTES,
    METHOD_ALIASES,
    METHOD_COOKING_OIL_TSP,
    METHOD_VEG_TIMING,
    SHOWN_AS,
    STAPLES,
    STYLE_INGREDIENTS,
    UNITS,
    VEGETABLE_DISH_TIMING,
    VEGETABLES,
)

from proteins import GENERIC_PROFILE, PROTEIN_ALIASES, PROTEINS

# Local keys live in .env. On Cloud Run they are environment variables.
load_dotenv()

FDC_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"


# Every item a flavor base can use. These season the dish, so they belong on the pantry shelf.
FLAVOR_ITEMS = set(FAT_G_PER_TSP)
for _base in FLAVOR_BASES:
    FLAVOR_ITEMS.update(_base["required"], _base["oil"], *_base["one_of"], *_base["optional"])


# Every name the tables know, for catching typos.
KNOWN_NAMES = [*PROTEINS, *VEGETABLES, *FLAVOR_ITEMS, *ALIASES, *PROTEIN_ALIASES]


def _clean(name) -> str:
    """Lowercase and trim a name, then map aliases, simple plurals and near-miss spellings to the names in the tables."""
    name = " ".join(str(name or "").lower().split())
    singular = name.removesuffix("s")
    for candidate in (name, singular):
        if candidate in ALIASES:
            return ALIASES[candidate]
        if candidate in PROTEIN_ALIASES:
            return PROTEIN_ALIASES[candidate]
    if name in PROTEINS or name in VEGETABLES or name in FLAVOR_ITEMS:
        return name
    if singular in PROTEINS or singular in VEGETABLES or singular in FLAVOR_ITEMS:
        return singular
    # A typo: "chiken thighs", "zuchini", "cummin". Only a close match counts, so short words are left alone.
    close = difflib.get_close_matches(name, KNOWN_NAMES, n=1, cutoff=0.85)
    return _clean(close[0]) if close else name


def _resolve(food) -> tuple[str, str]:
    """Turn whatever name the model sent into (everyday name, USDA search text)."""
    known = {**PROTEINS, **VEGETABLES}
    by_query = {info["usda_query"]: name for name, info in known.items()}
    name = _clean(food)
    if name in by_query:
        name = by_query[name]
    elif name not in known and name not in FLAVOR_ITEMS:
        # The model likes to add words such as "raw" or "boneless". Look for a known food inside the name.
        # Seasonings are left alone: "onion powder" is not an onion.
        # Plurals are ignored on both sides, so "pork rib" finds "pork ribs".
        words = {word.removesuffix("s") for word in name.split()}
        inside = [food for food in known if {word.removesuffix("s") for word in food.split()} <= words]
        if inside:
            name = max(inside, key=len)
    return name, known[name]["usda_query"] if name in known else name


def _number(value):
    """A float, or None when the value is missing or not a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_list(value) -> list:
    """Models sometimes send one string where a list is expected."""
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


# --- update_pantry ---


def update_pantry(pantry: list, add=None, remove=None) -> dict:
    """Add or remove items on this session's shelf. With no arguments it just reports the shelf."""
    added, removed, notes = [], [], []

    for item in map(_clean, _as_list(add)):
        if item in PROTEINS or item in VEGETABLES:
            # The shelf is for what seasons a dish. Proteins, vegetables and sides go to suggest_from_pantry.
            notes.append(f"{item} is not a pantry item: pass it to suggest_from_pantry as the protein or a vegetable")
        elif item in pantry:
            notes.append(f"{item} was already in the pantry")
        elif item:
            pantry.append(item)
            added.append(item)

    for item in map(_clean, _as_list(remove)):
        if item in pantry:
            pantry.remove(item)
            removed.append(item)
        else:
            notes.append(f"{item} was not in the pantry")

    return {
        "pantry": list(pantry),
        "added": added,
        "removed": removed,
        "notes": notes,
        "next_step": "If the user wants a recipe or one is in progress, call suggest_from_pantry now.",
    }


# --- suggest_from_pantry ---


def _amount(item: str, qty: float) -> str:
    """Format an amount with its item, e.g. 3 tsp of gochujang -> '1 tbsp gochujang'."""
    unit = UNITS.get(item, "tsp")
    if unit == "tsp" and qty >= 3 and qty % 1.5 == 0:
        qty, unit = qty / 3, "tbsp"
    elif unit != "tsp" and qty > 1:
        unit += "s"
    return f"{qty:g} {unit} {SHOWN_AS.get(item, item)}"


def _listed(items: dict) -> str:
    return ", ".join(_amount(item, qty) for item, qty in items.items())


def _build_sauce(base: dict, shelf: list) -> tuple[dict, list]:
    """Pick the items for one flavor base from the shelf. Returns (items, missing)."""
    items = dict(base["required"])
    missing = [item for item in base["required"] if item not in shelf]

    for group in base["one_of"]:
        choice = next((item for item in group if item in shelf), None)
        if choice is None:
            missing.append(" or ".join(group))
        else:
            items[choice] = group[choice]

    for group in base["optional"]:
        choice = next((item for item in group if item in shelf), None)
        if choice and choice not in items:
            items[choice] = group[choice]

    return items, missing


def _budget_oil(base: dict, method: str, shelf: list, max_fat_g: float, needs_oil: bool) -> tuple[dict, bool, str | None]:
    """Oil for one recipe in tsp per serving, cut back to fit the fat budget.

    Returns (oils, capped, cooking_oil). cooking_oil is the oil that goes in the pan, if the user has one.
    """
    wanted = {item: tsp for item, tsp in base["oil"].items() if item in shelf}
    cooking_oil = next((oil for oil in COOKING_OILS if oil in shelf), None)
    if METHOD_COOKING_OIL_TSP[method] and cooking_oil and needs_oil:
        wanted[cooking_oil] = wanted.get(cooking_oil, 0) + METHOD_COOKING_OIL_TSP[method]

    # Spend the budget on the sauce's own oil first (flavor), then on cooking oil, in quarter teaspoons.
    oils, left = {}, max_fat_g
    for item, tsp in wanted.items():
        affordable = int(left / FAT_G_PER_TSP[item] * 4) / 4
        if min(tsp, affordable) > 0:
            oils[item] = min(tsp, affordable)
            left -= oils[item] * FAT_G_PER_TSP[item]
    return oils, oils != wanted, cooking_oil if cooking_oil in oils else None


def _names(items: list) -> str:
    """'potato', 'potato and carrot', or 'potato, carrot and onion'."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _vegetable_steps(vegetables, base, method, sauce, oils, cooking_oil) -> list:
    """Cooking steps for a dish with no protein: the vegetables are seasoned and cooked themselves."""
    in_pan = bool(METHOD_COOKING_OIL_TSP[method])
    finishing = {item: tsp for item, tsp in oils.items() if not (in_pan and item == cooking_oil)}
    squeeze = {item: qty for item, qty in sauce.items() if item in SHOWN_AS and base["style"] == "rub"}
    mixed = {item: qty for item, qty in sauce.items() if item not in squeeze}
    by_kind = {kind: [v["name"] for v in vegetables if v["cook"] == kind] for kind in ("firm", "quick", "raw", "separate")}
    cooked = by_kind["firm"] + by_kind["quick"]
    steps = []

    if base["style"] == "glaze":
        steps.append(f"Whisk the sauce: {_listed(mixed)}. {base.get('sauce_note', '')}".strip())
    elif base["style"] == "rub":
        steps.append(f"Mix the seasoning: {_listed(mixed)}.")
    elif base["style"] == "braise":
        steps.append(f"Stir the braising liquid: {_listed(mixed)}, plus 1/4 cup water per serving.")
    else:
        steps.append(f"Stir the dressing: {_listed(mixed)}. Set it aside until the end.")

    if cooked:
        cut = f"Cut the {_names(cooked)} into even pieces"
        if base["style"] == "glaze":
            steps.append(f"{cut} and toss with half the sauce.")
        elif base["style"] == "rub":
            steps.append(f"{cut} and toss with the seasoning.")
        else:
            steps.append(cut + ".")

        timing = VEGETABLE_DISH_TIMING[method]
        heat = " ".join(part for part in (method.capitalize(), "the {}", timing["how"], "for {}.") if part)
        first = "firm" if by_kind["firm"] else "quick"
        cook = heat.format(_names(by_kind[first]), timing[first])
        if in_pan and cooking_oil:
            cook = f"Heat {_amount(cooking_oil, oils[cooking_oil])}. " + cook
        elif in_pan:
            cook = "Use a nonstick pan with a splash of water. " + cook
        if by_kind["firm"] and by_kind["quick"]:
            cook += f" Add the {_names(by_kind['quick'])} for the last {timing['quick'].split(',')[0]}."
        if base["style"] == "glaze":
            cook += " Toss with the rest of the sauce for the last 2 min."
        steps.append(cook)

    if by_kind["raw"] and not cooked and base["style"] in ("glaze", "rub"):
        # A salad: nothing is cooked, so the seasoning goes straight on.
        steps.append(f"Slice the {_names(by_kind['raw'])} and toss with the {'sauce' if base['style'] == 'glaze' else 'seasoning'}.")
    elif by_kind["raw"]:
        steps.append(f"Slice the {_names(by_kind['raw'])} and add raw.")
    if by_kind["separate"]:
        steps.append(f"Cook the {_names(by_kind['separate'])} separately and serve everything over it.")

    finish = []
    if base["style"] == "dressing":
        finish.append("Spoon the dressing over everything.")
    if squeeze:
        finish.append(f"Squeeze {_listed(squeeze)} over the top.")
    if finishing:
        finish.append(f"Finish with {_listed(finishing)}.")
    if finish:
        steps.append(" ".join(finish))
    return steps


def _vegetable_dish(vegetables: list) -> tuple[dict | None, dict | None]:
    """Stands in for the protein when there is none. Returns (info, error), like _protein_info."""
    if not vegetables:
        return None, {
            "error": "no vegetables or sides given",
            "suggestion": "Ask the user which vegetables or sides they want the dish made from.",
        }
    # Raw vegetables only (cucumber, scallion) make a salad. Anything else gets cooked.
    needs_heat = any(v["cook"] in ("firm", "quick") for v in vegetables)
    methods = list(VEGETABLE_DISH_TIMING) if needs_heat else ["no-cook"]
    return {"kind": "vegetable", "methods": dict.fromkeys(methods, "")}, None


def _steps(protein, info, vegetables, base, method, sauce, oils, cooking_oil) -> list:
    """Write the cooking steps for one recipe skeleton. sauce and oils are totals for the whole recipe."""
    in_pan = bool(METHOD_COOKING_OIL_TSP[method])
    no_cook = method == "no-cook"
    # Ground meat, eggs and beans get the seasoning stirred in; whole cuts get it rubbed on.
    stirred = info.get("coat") == "mix"
    finishing = {item: tsp for item, tsp in oils.items() if not (in_pan and item == cooking_oil)}
    # In a dry rub the citrus is squeezed on at the end instead of mixed in.
    squeeze = {item: qty for item, qty in sauce.items() if item in SHOWN_AS and base["style"] == "rub"}
    mixed = {item: qty for item, qty in sauce.items() if item not in squeeze}
    prep = info["prep"]
    steps = []

    if base["style"] == "glaze":
        steps.append(f"Whisk the sauce: {_listed(mixed)}. {base.get('sauce_note', '')}".strip())
        if no_cook:
            steps.append(f"{prep} Toss the {protein} with the sauce.".strip())
        elif stirred:
            steps.append(f"{prep} Stir half the sauce into the {protein}.".strip())
        else:
            steps.append(f"{prep} Coat the {protein} with half the sauce and rest 15 min.".strip())
    elif base["style"] == "rub":
        steps.append(f"Mix the seasoning: {_listed(mixed)}.")
        if stirred:
            steps.append(f"{prep} Stir the seasoning into the {protein}.".strip())
        else:
            steps.append(f"{prep} Pat the {protein} dry and rub the seasoning all over.".strip())
    elif base["style"] == "braise":
        steps.append(f"Stir the braising liquid: {_listed(mixed)}, plus 1/4 cup water per serving.")
        steps.append(prep or f"Prep the {protein}.")
    else:
        steps.append(f"Stir the dressing: {_listed(mixed)}. Set it aside until the end.")
        steps.append(prep or f"Prep the {protein}.")

    if no_cook:
        cook = f"No cooking needed: the {protein} is {info['methods'][method]}."
    else:
        cook = f"{method.capitalize()} the {protein}: {info['methods'][method]}."
    if in_pan and cooking_oil:
        cook = f"Heat {_amount(cooking_oil, oils[cooking_oil])}. " + cook
    elif in_pan and not info.get("needs_oil", True):
        cook = f"No oil needed: the {protein} cooks in its own fat. " + cook
    elif in_pan:
        cook = "Use a nonstick pan with a splash of water. " + cook
    if base["style"] == "glaze" and not no_cook:
        if method == "braise":
            cook += " Stir the rest of the sauce into the pot for the last 10 min."
        elif stirred or method == "stir-fry":
            cook += " Stir in the rest of the sauce for the last minute."
        else:
            cook += " Brush on the rest of the sauce for the last 2 min."
    steps.append(cook)

    # In a pan the vegetables are sequenced around the protein. Everywhere else they cook alongside it.
    timing = METHOD_VEG_TIMING[method]
    together = "" if in_pan else f", timed to finish with the {protein}"
    for kind in ("firm", "quick"):
        names = [v["name"] for v in vegetables if v["cook"] == kind]
        if names:
            steps.append(f"Cook the {' and '.join(names)} {timing[kind]}{together}.")
    raw = [v["name"] for v in vegetables if v["cook"] == "raw"]
    if raw:
        steps.append(f"Slice the {' and '.join(raw)} and serve raw on the side.")
    separate = [v["name"] for v in vegetables if v["cook"] == "separate"]
    if separate:
        steps.append(f"Cook the {' and '.join(separate)} separately and serve alongside.")

    finish = []
    if info["safe_temp_f"]:
        finish.append(f"Check the thickest part of the {protein} reaches {info['safe_temp_f']}°F.")
    if base["style"] == "dressing":
        finish.append("Spoon the dressing over everything.")
    if squeeze:
        finish.append(f"Squeeze {_listed(squeeze)} over the top.")
    if finishing:
        finish.append(f"Finish with {_listed(finishing)}.")
    if finish:
        steps.append(" ".join(finish))

    return steps


def _commonest(items) -> list:
    """The staples among these items, most common first. Specialty items are dropped."""
    return sorted((item for item in items if item in STAPLES), key=STAPLES.index)


def _flavor_boosts(base: dict, shelf: list, vegetables: list) -> dict:
    """Ideas for making a recipe taste better: what could be added, and what each would bring."""
    boosts = {}

    # Extras this flavor base can take that the user has not mentioned.
    ideas = []
    for group in base["optional"] + [base["oil"]]:
        names = _commonest(group)[:2]
        if names and not any(item in shelf for item in group):
            ideas.append(f"{' or '.join(names)}: adds {FLAVOR_NOTES.get(names[0], 'more flavor')}")
    if ideas:
        boosts["seasonings_for_this_recipe"] = ideas[:4]

    # Vegetables and sides, when the user named fewer than two.
    if len(vegetables) < 2:
        have = {v["name"] for v in vegetables}
        boosts["vegetables_and_sides_that_suit_it"] = [v for v in base["pairs_with"] if v not in have][:3]

    return boosts


# A food that is not in the table still counts as a protein if USDA shows it is protein-rich:
# enough protein by weight, and enough of its calories from protein. Together these keep out
# vegetables (little protein), bread and pasta (mostly starch) and nut butters (mostly fat).
MIN_PROTEIN_G_PER_100G = 10
MIN_PROTEIN_SHARE_OF_KCAL = 0.20


def _protein_info(protein: str) -> tuple[dict | None, dict | None]:
    """Cooking details for a protein. Returns (info, error); exactly one of them is None."""
    if protein in PROTEINS:
        return PROTEINS[protein], None

    asking = (
        "Do not choose a protein for the user and do not give a recipe yet. Ask the user which protein they "
        "have (any meat, poultry, fish, shellfish, eggs, tofu, beans or lentils), and whether they have any "
        "other seasonings or sauces. If they have already said they do not want a protein, or asked for a "
        "vegetable or side dish, call this tool again with no_protein set to true instead of asking."
    )
    if not protein:
        return None, {"error": "no protein given", "suggestion": asking}
    if protein in VEGETABLES or protein in FLAVOR_ITEMS:
        return None, {"error": f"'{protein}' is not a protein", "suggestion": asking}
    if not re.fullmatch(r"[a-z][a-z' -]{2,}", protein):
        # Numbers and stray symbols are not food names; do not send them to USDA.
        return None, {"error": f"'{protein}' is not a protein this tool recognises", "suggestion": asking}

    # Not in the table. Let USDA decide whether it is protein-rich enough to build a meal around.
    for query in (f"{protein} raw", protein):
        matches, error = _lookup(query)
        if error:
            return None, error
        if not matches:
            continue
        per = _best(matches)["per_100g"]
        share = per["protein_g"] * 4 / per["kcal"] if per["kcal"] else 0
        if per["protein_g"] >= MIN_PROTEIN_G_PER_100G and share >= MIN_PROTEIN_SHARE_OF_KCAL:
            return {**GENERIC_PROFILE, "usda_query": query}, None
    return None, {"error": f"'{protein}' is not a protein this tool recognises", "suggestion": asking}


def suggest_from_pantry(
    pantry: list,
    protein: str = "",
    vegetables=None,
    method: str | None = None,
    max_added_fat_g: float = DEFAULT_MAX_ADDED_FAT_G,
    must_use: str | None = None,
    servings: int = 1,
    no_protein: bool = False,
    flavor_base: str | None = None,
) -> dict:
    """Offer the dishes this shelf can make, or give one of them in full once the user has chosen.

    Everything is seasoned only with what is on this session's shelf.
    """
    # Vegetables cook alongside the protein. Anything that seasons the dish instead (lime, garlic,
    # ginger) counts as part of the shelf for this recipe, even if it arrived in the vegetables list.
    shelf, veg = list(pantry), []
    for name in map(_clean, _as_list(vegetables)):
        if name in FLAVOR_ITEMS:
            shelf.append(name)
        elif name:
            # Unknown vegetables are fine: treat them as quick-cooking.
            known_name = _resolve(name)[0]
            name = known_name if known_name in VEGETABLES else name
            veg.append({"name": name, **VEGETABLES.get(name, {"usda_query": f"{name} raw", "cook": "quick"})})

    # A dish is built around a protein unless the user has said they do not want one.
    protein, _ = _resolve(protein)
    meatless = bool(no_protein) and not protein
    info, error = _vegetable_dish(veg) if meatless else _protein_info(protein)
    if error:
        return error
    dish = _names([v["name"] for v in veg]) if meatless and len(veg) <= 2 else "vegetables" if meatless else protein

    if method:
        method = " ".join(method.lower().split())
        method = METHOD_ALIASES.get(method, method)
        if method not in METHOD_COOKING_OIL_TSP:
            return {
                "error": f"unknown method '{method}'",
                "suggestion": f"Use one of {list(METHOD_COOKING_OIL_TSP)}, or leave method out.",
            }
        if method not in info["methods"]:
            return {
                "error": f"{method} does not suit {dish}",
                "suggestion": f"Methods that suit {dish}: {list(info['methods'])}.",
            }

    try:
        max_added_fat_g = float(max_added_fat_g)
    except (TypeError, ValueError):
        max_added_fat_g = -1
    if max_added_fat_g < 0:
        return {
            "error": "max_added_fat_g must be a number of grams, 0 or more",
            "suggestion": f"Leave it out to use the default of {DEFAULT_MAX_ADDED_FAT_G} g (1 tsp of oil).",
        }

    # The rules table is per serving. Amounts are multiplied out here so the model does not have to.
    servings = min(max(int(_number(servings) or 1), 1), 12)

    must_use = _clean(must_use) if must_use else None
    must_use = STYLE_INGREDIENTS.get(must_use, must_use)
    if must_use and must_use not in shelf:
        return {
            "error": f"'{must_use}' is not in the pantry",
            "suggestion": f"Tell the user '{must_use}' is not among what they listed and ask if they have it. "
            f"The shelf has {shelf}.",
        }

    # Without cooking oil on the shelf, prefer a method that needs none, unless the cut cooks in its own fat.
    needs_oil = info.get("needs_oil", True)
    no_pan = needs_oil and not any(oil in shelf for oil in COOKING_OILS)

    # A flavor base the user picked by name, usually from the options this tool offered a moment ago.
    chosen_base = None
    if flavor_base:
        key = " ".join(str(flavor_base).lower().split())
        names = {base["name"].lower(): base for base in FLAVOR_BASES}
        chosen_base = names.get(key) or next((base for name, base in names.items() if key in name or name in key), None)
        if chosen_base is None:
            return {
                "error": f"unknown flavor base '{flavor_base}'",
                "suggestion": "Call this tool without flavor_base to get the options, then use one of their names.",
            }

    def build(base: dict, order: int, how: str, sauce: dict) -> dict | None:
        """One recipe: this flavor base, cooked this way. None if the oil budget or must_use rules it out."""
        oils, capped, cooking_oil = _budget_oil(base, how, shelf, max_added_fat_g, needs_oil)
        if base.get("oil_required") and not oils:
            return None
        if must_use and must_use not in sauce and must_use not in oils:
            return None
        core = set(base["required"]).union(*base["one_of"])
        fat = round(sum(tsp * FAT_G_PER_TSP[item] for item, tsp in oils.items()), 1)
        total = {item: qty * servings for item, qty in sauce.items()}
        oils = {item: tsp * servings for item, tsp in oils.items()}
        return {
            "base": base,
            "per_serving": sauce,
            # A base built around the requested item beats one that only uses it as an extra.
            "rank": (bool(must_use) and must_use not in core, info["kind"] not in base["best_with"], -len(sauce), order),
            "name": f"{base['name']} {dish} ({how})",
            "flavor_base": base["name"],
            "method": how,
            "seasoning": [_amount(item, qty) for item, qty in total.items()],
            "oil": [_amount(item, tsp) for item, tsp in oils.items()],
            "added_fat_g_per_serving": fat,
            "steps": _vegetable_steps(veg, base, how, total, oils, cooking_oil) if meatless
            else _steps(protein, info, veg, base, how, total, oils, cooking_oil),
            "notes": [f"Oil was cut back to stay within {max_added_fat_g:g} g of added fat per serving."] if capped else [],
        }

    # recipes: each flavor base cooked the way that suits the dish best. variants: the same bases cooked other ways.
    recipes, variants, could_unlock, makeable = [], [], [], []
    for order, base in enumerate(FLAVOR_BASES):
        # The protein's own order decides: its best method that this base also works with.
        fits = [m for m in info["methods"] if m in base["methods"] and method in (None, m)]
        if method is None and no_pan:
            fits = [m for m in fits if not METHOD_COOKING_OIL_TSP[m]] or fits
        sauce, missing = _build_sauce(base, shelf)
        if base.get("oil_required") and not any(oil in shelf for oil in base["oil"]):
            missing.append(" or ".join(base["oil"]))
        if missing:
            if base is chosen_base:
                return {
                    "error": f"{base['name']} needs {_names(missing)}, which is not in the pantry",
                    "suggestion": "Tell the user what is missing and ask if they have it, or offer the options again.",
                }
            # One item short of a base that suits this protein: worth asking the user about,
            # but only if the missing item is a common staple. Nobody is asked for gochujang.
            common = _commonest(missing[0].split(" or ")) if len(missing) == 1 else []
            if common and fits and info["kind"] in base["best_with"] and must_use in (None, *sauce):
                # How much of this base the user already has, not counting the salt and pepper everyone starts with.
                on_shelf = sum(item in shelf and item not in DEFAULT_PANTRY for item in sauce)
                could_unlock.append({
                    "flavor_base": base["name"],
                    "ask_user_if_they_have": " or ".join(common[:2]),
                    "order": (-on_shelf, STAPLES.index(common[0])),
                })
            continue
        makeable.append(base["name"])

        made = [recipe for recipe in (build(base, order, how, sauce) for how in fits) if recipe]
        recipes += made[:1]
        variants += made[1:]

    if not makeable:
        return {
            "error": "nothing on the shelf to season with",
            "suggestion": "Ask the user what seasonings or sauces they have, then call update_pantry to add them.",
        }
    # Bases that suit the protein come first, then the ones using more of the shelf.
    # The same goes for near misses: ask about the one the user is closest to.
    recipes.sort(key=lambda r: r["rank"])
    could_unlock.sort(key=lambda c: c["order"])
    could_unlock = [{k: v for k, v in c.items() if k != "order"} for c in could_unlock[:2]]

    if chosen_base:
        choices = [r for r in recipes if r["base"] is chosen_base]
    else:
        # Up to four different flavors. With fewer than three, add the best one cooked other ways,
        # so the user still has a real choice. Not when they named a flavor or a method: then they
        # have already said what they want.
        choices = recipes[:4]
        if recipes and len(choices) < 3 and not must_use and not method:
            choices += [v for v in variants if v["base"] is recipes[0]["base"]][: 3 - len(choices)]

    if not choices:
        possible = {
            base["name"]: [m for m in base["methods"] if m in info["methods"]]
            for base in FLAVOR_BASES
            if base["name"] in makeable
        }
        return {
            "error": "no flavor base fits those constraints",
            "constraints": {"method": method, "must_use": must_use, "flavor_base": flavor_base, "max_added_fat_g": max_added_fat_g},
            "could_unlock": could_unlock,
            "suggestion": "If could_unlock has an entry, ask the user whether they have that item. Otherwise loosen "
            f"one constraint. Bases this pantry can make for {dish}, with their methods: {possible}.",
        }

    result = {
        "protein": None if meatless else protein,
        "servings": servings,
        "vegetables": [v["name"] for v in veg],
        "shelf_used": shelf,
    }

    # More than one dish fits and the user has not picked: offer the choices, without steps.
    if len(choices) > 1:
        result["options"] = [
            {
                "number": number,
                "name": r["name"],
                "flavor_base": r["flavor_base"],
                "method": r["method"],
                "tastes": r["base"]["tastes"],
                "seasoning": r["seasoning"] + r["oil"],
            }
            for number, r in enumerate(choices, start=1)
        ]
        result["could_unlock"] = could_unlock
        result["next_step"] = (
            "The user has not chosen a dish yet. List every option. If could_unlock has entries, ask whether "
            "they have each item and say what it would let you make. Then ask which option they want. Give no "
            "steps or nutrition and do not call total_meal_macros. When they choose, call this tool again with "
            "flavor_base and method set to that option."
        )
        return result

    # One dish: the user's pick, or the only thing that fits. Give it in full.
    recipe = choices[0]
    boosts = _flavor_boosts(recipe["base"], shelf, veg)
    others = [r["flavor_base"] for r in recipes if r is not recipe]
    del recipe["rank"], recipe["base"], recipe["per_serving"]
    result.update({
        "amounts": f"Seasoning and oil amounts are totals for {servings} serving(s).",
        "max_added_fat_g_per_serving": max_added_fat_g,
        "recipes": [recipe],
        "other_flavors_possible": others,
        "next_step": "Before stating any macros, call total_meal_macros with the protein and each vegetable.",
    })
    if meatless:
        result["suggested_raw_g_per_vegetable_per_serving"] = DEFAULT_VEGETABLE_G_PER_SERVING
        result["next_step"] = "Before stating any macros, call total_meal_macros with each vegetable and side."
    else:
        result["suggested_raw_protein_g_per_serving"] = DEFAULT_PROTEIN_G_PER_SERVING
    if boosts:
        result["flavor_boosts"] = boosts
    return result


# --- get_nutrition ---

# USDA nutrient ids. Foundation foods often leave out 1008 and report Atwater energy instead.
ENERGY_IDS = (1008, 2048, 2047)
PROTEIN_ID, FAT_ID, CARB_ID = 1003, 1004, 1005
SATURATED_FAT_ID, FIBER_ID, SODIUM_ID = 1258, 1079, 1093
SUGAR_IDS = (2000, 1063)  # SR Legacy and Foundation use different ids for total sugars

# After USDA says "too many requests", stop asking for a minute instead of hammering it.
USDA_PAUSE_SECONDS = 60
usda_paused_until = 0.0


class RateLimited(Exception):
    """USDA is rate limiting us."""


@lru_cache(maxsize=256)
def _usda_search(food: str) -> list:
    """One USDA search per distinct food name. Raises on network trouble, so failures are never cached."""
    global usda_paused_until
    if time.time() < usda_paused_until:
        raise RateLimited()

    reply = requests.get(
        FDC_URL,
        params={
            # USDA rejects brackets, quotes and slashes in the search text.
            "query": " ".join(re.sub(r"[^\w\s%.-]", " ", food).split()),
            # Foundation and SR Legacy are lab-analysed whole foods. Branded is left out: too noisy.
            "dataType": "Foundation,SR Legacy",
            "requireAllWords": "true",
            "pageSize": 5,
            "api_key": os.environ.get("FDC_API_KEY", "DEMO_KEY"),
        },
        timeout=10,
    )
    if reply.status_code == 429:
        usda_paused_until = time.time() + USDA_PAUSE_SECONDS
        raise RateLimited()
    reply.raise_for_status()

    matches = []
    for item in reply.json().get("foods", []):
        nutrients = {n.get("nutrientId"): n.get("value") for n in item.get("foodNutrients", [])}
        protein, fat, carbs = (nutrients.get(i) for i in (PROTEIN_ID, FAT_ID, CARB_ID))
        if protein is None or fat is None:
            continue
        carbs = max(carbs or 0, 0)  # "by difference" carbs can come back slightly negative
        kcal = next((nutrients[i] for i in ENERGY_IDS if nutrients.get(i) is not None), None)
        if kcal is None:
            kcal = 4 * protein + 9 * fat + 4 * carbs
        matches.append({
            "description": item["description"],
            "fdc_id": item["fdcId"],
            "data_type": item["dataType"],
            "per_100g": {
                "kcal": kcal,
                "protein_g": protein,
                "fat_g": fat,
                "carbs_g": carbs,
                # These four are None when USDA does not report them for this food.
                "saturated_fat_g": nutrients.get(SATURATED_FAT_ID),
                "sugars_g": next((nutrients[i] for i in SUGAR_IDS if nutrients.get(i) is not None), None),
                "fiber_g": nutrients.get(FIBER_ID),
                "sodium_mg": nutrients.get(SODIUM_ID),
            },
        })
    return matches


def _lookup(food: str) -> tuple[list, dict | None]:
    """Search USDA and turn a service failure into an error the model can act on. Returns (matches, error)."""
    try:
        return _usda_search(food), None
    except RateLimited:
        return [], {
            "error": "nutrition service busy (USDA rate limit reached)",
            "suggestion": "Do not call this tool again in this turn. Give the rest of the answer and tell "
            "the user these numbers are unavailable right now. Do not estimate them.",
        }
    except requests.HTTPError as e:
        return [], {
            "error": f"nutrition service rejected the request (HTTP {e.response.status_code})",
            "suggestion": "Tell the user nutrition lookups are unavailable. Do not estimate the numbers.",
        }
    except requests.RequestException:
        return [], {
            "error": "nutrition service did not respond",
            "suggestion": "Tell the user the numbers are unavailable right now. Do not estimate them.",
        }


def _shown(value, scale: float = 1):
    """A nutrient value for display: rounded, or 'not reported' when USDA has no figure."""
    return "not reported" if value is None else round(value * scale, 1)


def _best(matches: list) -> dict:
    """The top USDA match, preferring one that reports saturated fat so meal totals are complete."""
    complete = [m for m in matches if m["per_100g"]["saturated_fat_g"] is not None]
    return (complete or matches)[0]


def get_nutrition(food: str = "", grams: float = 100, target_protein_g: float | None = None) -> dict:
    """Look up kcal, protein, fat, carbs and more for a whole food in USDA FoodData Central, scaled to grams.

    With target_protein_g, the weight is worked out here: the grams needed to supply that much protein.
    """
    name, food = _resolve(food)
    if not food:
        return {"error": "no food given", "suggestion": "Pass a plain ingredient name such as 'shrimp raw'."}
    try:
        grams = float(grams)
    except (TypeError, ValueError):
        grams = 0
    if not 0 < grams <= 5000:
        return {"error": "grams must be a number between 1 and 5000", "suggestion": "Use 100 for a per-100 g lookup."}

    matches, error = _lookup(food)
    if error:
        return error

    if not matches:
        return {
            "error": f"no USDA match for '{food}'",
            "suggestion": "Search one raw ingredient at a time with a plain name, e.g. 'chicken thigh raw' "
            "rather than a dish name. Bottled sauces are often not in this data: say so instead of estimating.",
        }

    best = _best(matches)
    target = _number(target_protein_g)
    if target and best["per_100g"]["protein_g"] > 0:
        # Round up to the next 5 g so the target is met, not just approached.
        grams = math.ceil(target / best["per_100g"]["protein_g"] * 100 / 5) * 5
    scaled = {key: _shown(value, grams / 100) for key, value in best["per_100g"].items()}
    return {
        "name": name,
        "matched": best["description"],
        "fdc_id": best["fdc_id"],
        "data_type": best["data_type"],
        "grams": grams,
        **scaled,
        "other_matches": [m["description"] for m in matches if m is not best][:2],
        "source": "USDA FoodData Central",
    }


# --- total_meal_macros ---

TOTAL_KEYS = ("kcal", "protein_g", "fat_g", "carbs_g", "saturated_fat_g", "sugars_g", "fiber_g", "sodium_mg")


def total_meal_macros(items=None, servings: int = 1, added_fat_g: float = 0, protein_target_g: float | None = None) -> dict:
    """Look up each ingredient of a meal and add up one serving.

    The harness does the lookups and the arithmetic, so the model never copies or multiplies numbers.
    The first item is the main protein: its weight is raised if a protein target needs it.
    """
    items = [item for item in (items if isinstance(items, list) else []) if isinstance(item, dict)]
    if not items:
        return {
            "error": "no items to total",
            "suggestion": "Pass the protein first and then each vegetable, each as {food, grams} for ONE serving.",
        }
    servings = min(max(int(_number(servings) or 1), 1), 12)

    rows, not_found = [], []
    for item in items:
        name, query = _resolve(item.get("food") or item.get("name") or "")
        grams = _number(item.get("grams"))
        if not name or not grams or not 0 < grams <= 5000:
            return {
                "error": f"'{name or 'item'}' needs a food name and a weight in grams between 1 and 5000",
                "suggestion": "Pass each item as {food, grams}, with grams for ONE serving.",
            }
        matches, error = _lookup(query)
        if error:
            return error
        if not matches:
            not_found.append(name)
            continue
        best = _best(matches)
        rows.append({"name": name, "matched": best["description"], "grams": grams, "per_100g": best["per_100g"]})

    if not rows:
        return {
            "error": f"no USDA match for {not_found}",
            "suggestion": "Use plain raw-ingredient names, e.g. 'chicken thigh', 'zucchini'. Do not estimate the numbers.",
        }

    result = {"servings": servings}

    # Protein target: work out how much the rest of the plate supplies, then size the main protein to cover the gap.
    target = _number(protein_target_g)
    main = rows[0]
    if target and main["per_100g"]["protein_g"] > 0:
        from_others = sum(row["per_100g"]["protein_g"] * row["grams"] / 100 for row in rows[1:])
        needed = math.ceil((target - from_others) / main["per_100g"]["protein_g"] * 100 / 5) * 5
        if needed > main["grams"]:
            result["protein_weight_raised"] = (
                f"{main['name']} raised from {main['grams']:g} g to {needed} g per serving to reach {target:g} g of protein."
            )
            main["grams"] = needed

    totals = dict.fromkeys(TOTAL_KEYS, 0.0)
    result["items"] = []
    for row in rows:
        scale = row["grams"] / 100
        for key in TOTAL_KEYS:
            totals[key] += (row["per_100g"][key] or 0) * scale
        result["items"].append({
            "name": row["name"],
            "matched": row["matched"],
            "grams_per_serving": row["grams"],
            "grams_for_all_servings": round(row["grams"] * servings),
            "kcal": round(row["per_100g"]["kcal"] * scale, 1),
            "protein_g": round(row["per_100g"]["protein_g"] * scale, 1),
        })

    # Oil from the recipe is pure fat: 9 kcal per gram.
    added_fat_g = max(_number(added_fat_g) or 0, 0)
    totals["fat_g"] += added_fat_g
    totals["kcal"] += added_fat_g * 9

    result["per_serving"] = {key: round(value, 1) for key, value in totals.items()}
    result["added_fat_g_included"] = added_fat_g
    result["note"] = (
        "These totals cover the items listed plus the added oil. Seasonings and sauces are not counted: "
        "salt and salty sauces add sodium, and sweeteners add sugars."
    )
    if target:
        result["protein_target_g"] = target
        result["meets_protein_target"] = totals["protein_g"] >= target
    if not_found:
        result["not_found"] = not_found
        result["suggestion"] = "Tell the user these items were not found in USDA data and are missing from the totals."
    return result


# What the model sees: the "set notes" in the screenplay.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "suggest_from_pantry",
            "description": (
                "Work out what the user can cook from a protein and vegetables, seasoned only with what is "
                "on their pantry shelf, with oil held to a per-serving fat budget. The shelf starts with just "
                "salt and black pepper and grows only through update_pantry. Call this whenever the user asks "
                "what to cook, asks for a recipe or for other options, picks an option, or changes the "
                "protein, vegetables or pantry of an earlier recipe. Never write a recipe without calling it. "
                "It answers in one of two ways. When several dishes fit and the user has not chosen, it "
                "returns options: list them and ask which they want. When flavor_base names their choice, or "
                "only one dish fits, it returns recipes with one full recipe, amounts already multiplied for "
                "the servings. With options, could_unlock lists a dish that is one common ingredient short, "
                "to ask the user about. With a full recipe, flavor_boosts lists extras that would improve "
                "the dish and what each adds: suggestions, not questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "protein": {
                        "type": "string",
                        "description": "The one protein the user said they have, in their words, e.g. 'pork ribs', "
                        "'chicken thigh', 'salmon', 'eggs', 'black beans'. Any meat, poultry, fish, shellfish, egg, "
                        "tofu or legume works. Never a vegetable, rice or potatoes, and never one the user did not name.",
                    },
                    "vegetables": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Only the vegetables and sides the user said they have, e.g. ['zucchini', "
                        "'mushroom', 'rice', 'potato']. Never add ones they did not mention. Leave empty if they named none.",
                    },
                    "method": {
                        "type": "string",
                        "description": "Cooking method, only if the user asked for one: bake, air-fry, grill, "
                        "braise, poach, steam, stir-fry, pan-sear or no-cook.",
                    },
                    "max_added_fat_g": {
                        "type": "number",
                        "description": "Most grams of fat from oil allowed per serving. Default 4.5 (1 tsp of oil). "
                        "Use 0 for no oil at all.",
                    },
                    "must_use": {
                        "type": "string",
                        "description": "A pantry item the seasoning has to feature, only if the user asked for "
                        "a dish built around it, e.g. 'paprika' or 'lemon'.",
                    },
                    "servings": {"type": "integer", "description": "How many people the recipe feeds. Default 1."},
                    "flavor_base": {
                        "type": "string",
                        "description": "The flavor_base of the option the user chose, exactly as this tool listed "
                        "it, e.g. 'Paprika rub'. Pass method from the same option too. Leave flavor_base out when "
                        "the user has not chosen a dish yet or asks for alternatives.",
                    },
                    "no_protein": {
                        "type": "boolean",
                        "description": "Set to true, and leave protein out, only when the user has said they do not "
                        "want a protein or has asked for a vegetable dish or side dish. The recipe is then built "
                        "around the vegetables. Never set it just because no protein was mentioned.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_nutrition",
            "description": (
                "Look up real nutrition facts (kcal, protein, fat, carbs) for a whole food from USDA "
                "FoodData Central, scaled to a given weight. It also returns saturated fat, sugars, fiber "
                "and sodium when USDA reports them. Call this whenever you state a nutrition "
                "number; never estimate macros yourself. Use plain raw-ingredient names ('chicken thigh "
                "boneless skinless raw', 'shrimp raw', 'zucchini raw'), not dish names. Pass the weight "
                "for ONE serving. If the user wants a protein amount per serving, pass target_protein_g "
                "instead of grams and the tool works out the weight."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "food": {"type": "string", "description": "Plain ingredient name, e.g. 'salmon atlantic raw'."},
                    "grams": {"type": "number", "description": "Weight in grams to scale to. Default 100."},
                    "target_protein_g": {
                        "type": "number",
                        "description": "Grams of protein wanted from this food, e.g. 40. The tool then picks "
                        "the weight that supplies it and ignores grams. Use for the main protein only.",
                    },
                },
                "required": ["food"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "total_meal_macros",
            "description": (
                "Work out the per-serving nutrition of a meal: it looks up every ingredient in USDA "
                "FoodData Central, adds them up with the recipe's oil, and sizes the protein to hit a "
                "protein target. Call this right after suggest_from_pantry, before you state any numbers "
                "for a recipe. Do not call get_nutrition for recipe ingredients and never add macros up "
                "yourself. Report the weights and totals exactly as it returns them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "The main protein FIRST if the dish has one, then each vegetable or side.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "food": {"type": "string", "description": "Ingredient name, e.g. 'chicken thigh', 'zucchini'."},
                                "grams": {
                                    "type": "number",
                                    "description": "Weight for ONE serving, not the whole recipe. Use about 170 for the "
                                    "protein and 100 for each vegetable or side unless the user gave weights. "
                                    "Rice and quinoa are cooked weights; everything else is raw.",
                                },
                            },
                            "required": ["food", "grams"],
                        },
                    },
                    "servings": {"type": "integer", "description": "Number of servings in the recipe. Default 1."},
                    "added_fat_g": {
                        "type": "number",
                        "description": "added_fat_g_per_serving from the chosen suggest_from_pantry recipe. Default 0.",
                    },
                    "protein_target_g": {
                        "type": "number",
                        "description": "Protein per serving the user asked for, if any, e.g. 40. The tool raises "
                        "the protein's weight to reach it.",
                    },
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_pantry",
            "description": (
                "Add or remove items on the user's pantry shelf for this session, and return the updated "
                "shelf. The shelf starts with only salt and black pepper. Call this FIRST whenever the "
                "user names seasonings, spices, sauces, oils, vinegars, sweeteners, citrus, garlic or "
                "ginger they have, and whenever they say they ran out of or bought something ('I have "
                "paprika and garlic powder', 'I'm out of mirin'). Do not add the protein, fresh vegetables, "
                "rice or potatoes here: those go to suggest_from_pantry. Call it with no arguments to read "
                "the current shelf."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "add": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Items to put on the shelf, one per entry, e.g. ['paprika', 'garlic powder', 'lime'].",
                    },
                    "remove": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Items to take off the shelf, e.g. ['mirin'].",
                    },
                },
            },
        },
    },
]

# What the harness runs: tool name -> Python function.
TOOL_MAP = {
    "suggest_from_pantry": suggest_from_pantry,
    "get_nutrition": get_nutrition,
    "total_meal_macros": total_meal_macros,
    "update_pantry": update_pantry,
}

# These tools read or change the session's pantry. The harness passes it in; the model never does.
PANTRY_TOOLS = {"suggest_from_pantry", "update_pantry"}


def run_tool(name: str, args: dict, pantry: list) -> str:
    """Run one tool call. Models invent tool names and arguments; never let that crash the loop."""
    if name not in TOOL_MAP:
        return json.dumps({"error": f"Unknown tool '{name}'. Available: {list(TOOL_MAP)}"})
    try:
        if name in PANTRY_TOOLS:
            result = TOOL_MAP[name](pantry, **args)
        else:
            result = TOOL_MAP[name](**args)
    except TypeError as e:
        result = {"error": f"Bad arguments for {name}: {e}", "suggestion": "Check the argument names and types."}
    except Exception as e:
        result = {"error": f"{name} failed: {type(e).__name__}", "suggestion": "Tell the user this tool is unavailable."}
    return json.dumps(result, ensure_ascii=False)
