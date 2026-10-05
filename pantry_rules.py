"""The rules table behind suggest_from_pantry: the shelf, the vegetables, and the flavor bases.

The proteins are in proteins.py.

This file is data only. The logic that reads it lives in tools.py.
"""

# The shelf every new session starts with. Everything else has to come from the user,
# through update_pantry. Each session changes its own copy.
DEFAULT_PANTRY = ["salt", "black pepper"]

# Other ways people say the same pantry item, vegetable or protein.
ALIASES = {
    "pepper": "black pepper",
    "ground pepper": "black pepper",
    "ground black pepper": "black pepper",
    "kosher salt": "salt",
    "sea salt": "salt",
    "peppers": "bell pepper",
    "green pepper": "bell pepper",
    "red pepper": "bell pepper",
    "yellow pepper": "bell pepper",
    "green bell pepper": "bell pepper",
    "red bell pepper": "bell pepper",
    "lime juice": "lime",
    "lemon juice": "lemon",
    "potatoes": "potato",
    "tomatoes": "tomato",
    "brussels sprouts": "brussels sprout",
    "green peas": "peas",
    "sweet potatoes": "sweet potato",
    "white rice": "rice",
    "green onion": "scallion",
    "spring onion": "scallion",
    "garlic clove": "garlic",
    "fresh garlic": "garlic",
    "minced garlic": "garlic",
    "fresh ginger": "ginger",
    "smoked paprika": "paprika",
    "italian herbs": "italian seasoning",
    "chili flakes": "red pepper flakes",
    "crushed red pepper": "red pepper flakes",
    "dijon": "mustard",
    "dijon mustard": "mustard",
    "oil": "vegetable oil",
    "cooking oil": "vegetable oil",
    "neutral oil": "vegetable oil",
    "extra virgin olive oil": "olive oil",
    "evoo": "olive oil",
    "balsamic": "balsamic vinegar",
    "cooking wine": "chinese cooking wine",
    "shaoxing wine": "chinese cooking wine",
    "shaoxing": "chinese cooking wine",
    "rice wine": "chinese cooking wine",
    "soy": "soy sauce",
    "chilli crisp": "chili crisp",
    "chili crunch": "chili crisp",
    "chilli oil": "chili oil",
    "korean chili flakes": "gochugaru",
    "korean chili paste": "gochujang",
    "barbecue sauce": "bbq sauce",
    "barbeque sauce": "bbq sauce",
    "cider vinegar": "apple cider vinegar",
    "dry mustard": "mustard powder",
    "ground mustard": "mustard powder",
}

# A style of dish and the pantry item it depends on. Used only when the user asks for a dish by
# style ("bbq ribs"): the word is not treated as something they have.
STYLE_INGREDIENTS = {
    "bbq": "bbq sauce",
    "barbecue": "bbq sauce",
    "barbeque": "bbq sauce",
}

# Oil-based components count against the added-fat budget. Grams of fat per teaspoon (approximate).
FAT_G_PER_TSP = {
    "sesame oil": 4.5,
    "olive oil": 4.5,
    "avocado oil": 4.5,
    "vegetable oil": 4.5,
    "canola oil": 4.5,
    "chili oil": 4.5,
    "chili crisp": 3.5,
}

# Oils that can go in a hot pan, in order of preference. Used only if the user has one.
COOKING_OILS = ["olive oil", "avocado oil", "vegetable oil", "canola oil"]

# 1 tsp of oil per serving.
DEFAULT_MAX_ADDED_FAT_G = 4.5

# Everything is measured in teaspoons except these.
UNITS = {"garlic": "clove"}

# How an item is written in a recipe when that differs from its pantry name.
SHOWN_AS = {"lime": "lime juice", "lemon": "lemon juice"}

# Cooking oil a method needs, in tsp per serving. Taken from the same fat budget as the sauce.
METHOD_COOKING_OIL_TSP = {
    "bake": 0,
    "air-fry": 0,
    "grill": 0,
    "braise": 0,
    "poach": 0,
    "steam": 0,
    "no-cook": 0,
    "stir-fry": 0.5,
    "pan-sear": 0.5,
}

# Other ways people say a cooking method.
METHOD_ALIASES = {
    "roast": "bake",
    "oven": "bake",
    "air fry": "air-fry",
    "airfry": "air-fry",
    "air fryer": "air-fry",
    "stir fry": "stir-fry",
    "stirfry": "stir-fry",
    "saute": "pan-sear",
    "sear": "pan-sear",
    "pan sear": "pan-sear",
    "pan-fry": "pan-sear",
    "simmer": "braise",
    "stew": "braise",
    "boil": "poach",
    "broil": "bake",
    "smoke": "grill",
    "bbq": "grill",
    "barbecue": "grill",
    "fry": "pan-sear",
    "slow cook": "braise",
    "slow-cook": "braise",
    "no cook": "no-cook",
    "cold": "no-cook",
}

# How long the vegetables cook, per method. "firm" ones need longer than "quick" ones.
METHOD_VEG_TIMING = {
    "bake": {"firm": "on the same tray for 20-25 min", "quick": "on the same tray for 8-10 min"},
    "air-fry": {"firm": "in the basket for 10-12 min", "quick": "in the basket for 5-6 min"},
    "grill": {"firm": "on the grill for 8-10 min", "quick": "on the grill for 4-5 min"},
    "stir-fry": {"firm": "in the pan for 3-4 min before the protein", "quick": "in the pan for the last 2-3 min"},
    "pan-sear": {
        "firm": "in the same pan with a splash of water for 5-6 min once the protein is out",
        "quick": "in the same pan for 2-3 min once the protein is out",
    },
    "braise": {"firm": "in the pot for 10 min", "quick": "in the pot for 4-5 min"},
    "poach": {"firm": "simmered for 5-6 min", "quick": "simmered for 2-3 min"},
    "steam": {"firm": "in the steamer for 6-8 min", "quick": "in the steamer for 3-4 min"},
    "no-cook": {"firm": "steamed or boiled for 6-8 min", "quick": "steamed or boiled for 3-4 min"},
}

# Raw weight of protein per serving to start from. The model raises it to hit a protein target.
DEFAULT_PROTEIN_G_PER_SERVING = 170

# Vegetables and starchy sides.
# cook: "firm" ones go in early, "quick" ones near the end, "raw" ones are served uncooked, and
# "separate" ones (rice, quinoa) are cooked on their own. Weights for "separate" sides are cooked weights.
VEGETABLES = {
    "potato": {"usda_query": "potatoes flesh and skin raw", "cook": "firm"},
    "sweet potato": {"usda_query": "sweet potato raw unprepared", "cook": "firm"},
    "rice": {"usda_query": "rice white long-grain regular enriched cooked", "cook": "separate"},
    "brown rice": {"usda_query": "rice brown long-grain cooked", "cook": "separate"},
    "quinoa": {"usda_query": "quinoa cooked", "cook": "separate"},
    "tomato": {"usda_query": "tomatoes red ripe raw year round average", "cook": "quick"},
    "corn": {"usda_query": "corn sweet yellow raw", "cook": "quick"},
    "cauliflower": {"usda_query": "cauliflower raw", "cook": "firm"},
    "kale": {"usda_query": "kale raw", "cook": "quick"},
    "brussels sprout": {"usda_query": "brussels sprouts raw", "cook": "firm"},
    "peas": {"usda_query": "peas green raw", "cook": "quick"},
    "zucchini": {"usda_query": "squash summer zucchini includes skin raw", "cook": "quick"},
    "mushroom": {"usda_query": "mushrooms white raw", "cook": "quick"},
    "bok choy": {"usda_query": "cabbage chinese pak-choi raw", "cook": "quick"},
    "spinach": {"usda_query": "spinach raw", "cook": "quick"},
    "bell pepper": {"usda_query": "peppers sweet red raw", "cook": "quick"},
    "asparagus": {"usda_query": "asparagus raw", "cook": "quick"},
    "cabbage": {"usda_query": "cabbage raw", "cook": "quick"},
    "broccoli": {"usda_query": "broccoli raw", "cook": "firm"},
    "carrot": {"usda_query": "carrots raw", "cook": "firm"},
    "green bean": {"usda_query": "beans snap green raw", "cook": "firm"},
    "onion": {"usda_query": "onions raw", "cook": "firm"},
    "eggplant": {"usda_query": "eggplant raw", "cook": "firm"},
    "cucumber": {"usda_query": "cucumber with peel raw", "cook": "raw"},
    "scallion": {"usda_query": "onions spring or scallions raw", "cook": "raw"},
}

# A dish with no protein is built around the vegetables themselves.
# how: the heat for each method. firm and quick: how long each kind of vegetable takes.
VEGETABLE_DISH_TIMING = {
    "bake": {"how": "at 425°F", "firm": "25-30 min, turning once", "quick": "12-15 min"},
    "stir-fry": {"how": "over high heat", "firm": "6-8 min", "quick": "3-4 min"},
    "air-fry": {"how": "at 390°F", "firm": "14-16 min, shaking once", "quick": "8-10 min"},
    "grill": {"how": "over medium-high heat", "firm": "10-12 min, turning", "quick": "5-6 min, turning"},
    "pan-sear": {"how": "over medium-high heat", "firm": "8-10 min", "quick": "4-5 min"},
    "steam": {"how": "", "firm": "8-10 min", "quick": "4-5 min"},
    "braise": {"how": "in a covered pan with the liquid or a splash of water", "firm": "15-20 min", "quick": "6-8 min"},
    "poach": {"how": "in simmering water", "firm": "8-10 min", "quick": "3-4 min"},
}

# Raw weight of each vegetable per serving when the vegetables are the whole dish.
DEFAULT_VEGETABLE_G_PER_SERVING = 150

# Seasonings a home cook is likely to have, most common first. Sous Shelf only asks "do you have ...?"
# about these, and names them first when suggesting extras. Specialty items (gochujang, fish sauce,
# chili crisp and so on) are used when the user lists them, but never asked about or pushed.
STAPLES = [
    "garlic", "olive oil", "sugar", "garlic powder", "lemon", "paprika", "honey", "soy sauce", "vegetable oil",
    "onion powder", "mustard", "brown sugar", "lime", "cumin", "chili powder", "oregano", "italian seasoning",
    "balsamic vinegar", "bbq sauce", "red pepper flakes", "thyme", "rosemary", "ginger", "rice vinegar",
    "apple cider vinegar", "sesame oil", "cayenne", "canola oil", "avocado oil", "maple syrup", "mustard powder",
    "ground ginger",
]

# What an ingredient brings to a dish. Used when suggesting things the user could add.
FLAVOR_NOTES = {
    "garlic": "savory depth",
    "garlic powder": "savory depth",
    "onion powder": "a sweet, savory backbone",
    "ginger": "a fresh, zingy bite",
    "black pepper": "gentle heat",
    "lime": "brightness to cut the richness",
    "lemon": "brightness to cut the richness",
    "rice vinegar": "a clean tang",
    "apple cider vinegar": "a fruity tang",
    "soy sauce": "salty umami",
    "mirin": "sweetness that helps it caramelize",
    "sugar": "sweetness that helps it caramelize",
    "brown sugar": "a caramel sweetness and a better crust",
    "honey": "sweetness and a sticky glaze",
    "gochugaru": "smoky heat",
    "red pepper flakes": "heat",
    "chili powder": "warm, mild heat",
    "cumin": "earthy warmth",
    "oregano": "an herbal note",
    "mustard powder": "a sharp edge",
    "chinese cooking wine": "depth and aroma",
    "sesame oil": "a nutty aroma to finish",
    "olive oil": "richness and better browning",
    "chili oil": "heat and richness",
    "chili crisp": "crunchy heat",
}

# Each flavor base is a sauce or seasoning that can be built from pantry items alone.
#   required: every item must be on the shelf. Amounts are tsp per serving.
#   one_of:   each group needs one item on the shelf; the first one found is used.
#   optional: each group adds its first item found on the shelf, or nothing.
#   oil:      oil-based components, counted against the added-fat budget.
#   oil_required: True when the base makes no sense without its oil.
#   best_with: the kinds of protein the base suits (kinds are listed in proteins.py), plus
#              "vegetable" when it also works on vegetables alone.
#   pairs_with: vegetables and sides that go well with it, suggested when the user has few.
#   sauce_note: an extra instruction for making the sauce.
#   tastes:   a few words on the flavor, shown when the user is choosing between options.
#   style:    "glaze" goes on before cooking, "rub" is a dry seasoning, "braise" is the cooking
#             liquid, "dressing" goes on after.

# Optional groups that several bases share.
GARLIC = {"garlic": 1, "garlic powder": 0.25}
GARLIC_POWDER = {"garlic powder": 0.5, "garlic": 1}
GINGER = {"ginger": 1, "ground ginger": 0.25}
CITRUS = {"lime": 1, "lemon": 1}
BLACK_PEPPER = {"black pepper": 0.25}
HEAT = {"gochugaru": 0.5, "red pepper flakes": 0.25, "cayenne": 0.125}

FLAVOR_BASES = [
    {
        "name": "Gochujang glaze",
        "tastes": "sweet, spicy and sticky",
        "style": "glaze",
        "required": {"gochujang": 3, "soy sauce": 2},
        "one_of": [],
        "optional": [{"mirin": 2, "sugar": 1, "honey": 1}, {"rice vinegar": 1, "lime": 1}, HEAT, GARLIC, GINGER],
        "oil": {"sesame oil": 0.5},
        "methods": ["bake", "air-fry", "grill", "stir-fry", "pan-sear"],
        "best_with": ["vegetable", "poultry", "pork", "beef", "shellfish", "oily fish", "plant"],
        "pairs_with": ["zucchini", "mushroom", "scallion", "rice"],
    },
    {
        "name": "Sweet soy glaze",
        "tastes": "salty-sweet and glossy",
        "style": "glaze",
        "required": {"soy sauce": 3},
        "one_of": [{"mirin": 3, "sugar": 1.5, "honey": 1.5, "brown sugar": 1.5}],
        "optional": [{"chinese cooking wine": 2}, GARLIC, GINGER],
        "oil": {"sesame oil": 0.5},
        "methods": ["pan-sear", "bake", "grill", "air-fry", "stir-fry"],
        "best_with": ["vegetable", "oily fish", "lean fish", "poultry", "pork", "beef", "plant"],
        "pairs_with": ["broccoli", "bok choy", "rice"],
    },
    {
        "name": "Cooking-wine and soy braise",
        "tastes": "savory and tender, in a light broth",
        "style": "braise",
        "required": {"chinese cooking wine": 6, "soy sauce": 3},
        "one_of": [],
        "optional": [{"sugar": 1}, HEAT, GARLIC, GINGER],
        "oil": {},
        "methods": ["braise"],
        "best_with": ["vegetable", "poultry", "pork", "beef", "lamb", "lean fish", "plant", "offal"],
        "pairs_with": ["mushroom", "bok choy", "carrot"],
    },
    {
        "name": "Fish sauce and rice vinegar dressing",
        "tastes": "tangy, salty and fresh",
        "style": "dressing",
        "required": {"fish sauce": 2, "sugar": 1},
        "one_of": [{"rice vinegar": 3, "lime": 3}],
        "optional": [HEAT, GARLIC],
        "oil": {},
        "methods": ["grill", "air-fry", "poach", "steam", "bake", "stir-fry", "no-cook"],
        "best_with": ["vegetable", "shellfish", "pork", "poultry", "lean fish", "beef", "ready"],
        "pairs_with": ["cucumber", "cabbage", "rice"],
    },
    {
        "name": "Balsamic reduction",
        "tastes": "sweet-sharp and syrupy",
        "style": "glaze",
        "required": {"balsamic vinegar": 6},
        "one_of": [],
        "optional": [{"soy sauce": 1}, {"sugar": 0.5, "honey": 0.5}, GARLIC],
        "oil": {"olive oil": 0.5},
        "sauce_note": "Simmer the sauce in a small pan for 3-4 min until syrupy before using it.",
        "methods": ["pan-sear", "bake", "grill", "air-fry"],
        "best_with": ["vegetable", "poultry", "pork", "beef", "lamb", "game", "oily fish"],
        "pairs_with": ["asparagus", "mushroom", "potato"],
    },
    {
        "name": "Chili-crisp vinegar",
        "tastes": "tangy, with crunchy heat",
        "style": "dressing",
        "required": {},
        "one_of": [{"rice vinegar": 2, "balsamic vinegar": 2, "lime": 2}],
        "optional": [{"soy sauce": 1}, {"sugar": 0.5}],
        "oil": {"chili crisp": 1},
        "oil_required": True,
        "methods": ["poach", "steam", "air-fry", "bake", "grill", "no-cook"],
        "best_with": ["vegetable", "shellfish", "lean fish", "poultry", "pork", "plant", "egg", "ready"],
        "pairs_with": ["cucumber", "bok choy", "rice"],
    },
    {
        "name": "Gochugaru and fish sauce marinade",
        "tastes": "smoky, salty heat",
        "style": "glaze",
        "required": {"gochugaru": 1, "fish sauce": 2},
        "one_of": [{"sugar": 1, "mirin": 2, "honey": 1}],
        "optional": [{"rice vinegar": 1, "lime": 1}, GARLIC, GINGER],
        "oil": {"sesame oil": 0.5},
        "methods": ["stir-fry", "grill", "air-fry", "pan-sear"],
        "best_with": ["vegetable", "pork", "shellfish", "beef", "poultry"],
        "pairs_with": ["cabbage", "scallion", "rice"],
    },
    {
        "name": "Sesame-soy vinegar dressing",
        "tastes": "nutty, salty and light",
        "style": "dressing",
        "required": {"soy sauce": 2},
        "one_of": [{"rice vinegar": 2, "lime": 2}],
        "optional": [{"sugar": 0.5}, HEAT, GARLIC],
        "oil": {"sesame oil": 0.5, "chili oil": 0.5},
        "oil_required": True,
        "methods": ["poach", "steam", "bake", "air-fry", "no-cook"],
        "best_with": ["vegetable", "poultry", "shellfish", "lean fish", "oily fish", "plant", "egg", "legume", "ready"],
        "pairs_with": ["cucumber", "spinach", "rice"],
    },
    {
        "name": "BBQ sauce glaze",
        "tastes": "sticky, smoky and sweet",
        "style": "glaze",
        "required": {"bbq sauce": 6},
        "one_of": [],
        "optional": [{"apple cider vinegar": 1, "rice vinegar": 1}, {"garlic powder": 0.25}, {"red pepper flakes": 0.25, "cayenne": 0.125}],
        "oil": {},
        "methods": ["bake", "grill", "air-fry", "braise", "pan-sear"],
        "best_with": ["vegetable", "pork", "beef", "poultry", "lamb", "game", "plant"],
        "pairs_with": ["potato", "cabbage", "corn"],
    },
    {
        "name": "BBQ dry rub",
        "tastes": "a smoky-sweet crust",
        "style": "rub",
        "required": {"paprika": 1, "salt": 0.25},
        "one_of": [{"brown sugar": 1, "sugar": 1}],
        "optional": [
            GARLIC_POWDER,
            {"onion powder": 0.5},
            BLACK_PEPPER,
            {"chili powder": 0.5, "cayenne": 0.125},
            {"cumin": 0.25},
            {"mustard powder": 0.25},
        ],
        "oil": {},
        "methods": ["bake", "grill", "air-fry", "braise", "pan-sear"],
        "best_with": ["vegetable", "pork", "beef", "poultry", "lamb", "game"],
        "pairs_with": ["sweet potato", "corn", "green bean"],
    },
    {
        "name": "Paprika rub",
        "tastes": "smoky and savory",
        "style": "rub",
        "required": {"paprika": 1, "salt": 0.25},
        "one_of": [],
        "optional": [GARLIC_POWDER, {"onion powder": 0.5}, BLACK_PEPPER, {"cumin": 0.5}, {"brown sugar": 0.5}, CITRUS],
        "oil": {},
        "methods": ["bake", "air-fry", "grill", "pan-sear"],
        "best_with": ["vegetable", "pork", "poultry", "shellfish", "lean fish", "oily fish", "beef", "lamb", "game", "legume", "dairy"],
        "pairs_with": ["bell pepper", "onion", "potato"],
    },
    {
        "name": "Citrus-garlic marinade",
        "tastes": "bright and garlicky",
        "style": "glaze",
        "required": {"salt": 0.25},
        "one_of": [{"lime": 3, "lemon": 3}, {"garlic": 2, "garlic powder": 0.5}],
        "optional": [BLACK_PEPPER, {"cumin": 0.5, "paprika": 0.5}, {"honey": 1}, {"oregano": 0.5, "italian seasoning": 0.5}],
        "oil": {},
        "methods": ["grill", "pan-sear", "bake", "air-fry", "stir-fry", "no-cook"],
        "best_with": ["vegetable", "shellfish", "poultry", "lean fish", "oily fish", "pork", "lamb", "legume", "ready", "dairy"],
        "pairs_with": ["asparagus", "zucchini", "rice"],
    },
    {
        "name": "Cumin-chili rub",
        "tastes": "warm, earthy spice",
        "style": "rub",
        "required": {"cumin": 0.5, "salt": 0.25},
        "one_of": [{"chili powder": 1, "paprika": 1}],
        "optional": [GARLIC_POWDER, {"onion powder": 0.5}, {"oregano": 0.25}, BLACK_PEPPER, CITRUS],
        "oil": {},
        "methods": ["pan-sear", "grill", "bake", "air-fry", "stir-fry"],
        "best_with": ["vegetable", "beef", "poultry", "shellfish", "pork", "lean fish", "lamb", "game", "legume", "plant"],
        "pairs_with": ["bell pepper", "onion", "corn"],
    },
    {
        "name": "Herb rub",
        "tastes": "herby and simple",
        "style": "rub",
        "required": {"salt": 0.25},
        "one_of": [{"italian seasoning": 1, "oregano": 0.5, "thyme": 0.5, "rosemary": 0.5}],
        "optional": [GARLIC_POWDER, BLACK_PEPPER, {"lemon": 1, "lime": 1}],
        "oil": {},
        "methods": ["bake", "pan-sear", "grill", "air-fry", "no-cook"],
        "best_with": ["vegetable", "poultry", "pork", "oily fish", "lean fish", "lamb", "beef", "game", "dairy", "egg"],
        "pairs_with": ["potato", "green bean", "tomato"],
    },
    {
        "name": "Honey-mustard glaze",
        "tastes": "sweet and sharp",
        "style": "glaze",
        "required": {"mustard": 2},
        "one_of": [{"honey": 1, "maple syrup": 1, "brown sugar": 0.5, "sugar": 0.5}],
        "optional": [GARLIC, BLACK_PEPPER, {"lemon": 1, "rice vinegar": 0.5, "balsamic vinegar": 0.5}],
        "oil": {},
        "methods": ["bake", "air-fry", "grill", "pan-sear", "no-cook"],
        "best_with": ["vegetable", "poultry", "oily fish", "pork", "ready"],
        "pairs_with": ["broccoli", "carrot", "potato"],
    },
    {
        # The fallback: always possible from the starting shelf, so it suits everything and nothing in particular.
        "name": "Salt and pepper",
        "tastes": "plain and simple, so the ingredients do the talking",
        "style": "rub",
        "required": {"salt": 0.25, "black pepper": 0.25},
        "one_of": [],
        "optional": [GARLIC_POWDER, {"onion powder": 0.25}, CITRUS],
        "oil": {},
        "methods": ["bake", "air-fry", "grill", "pan-sear", "stir-fry", "poach", "steam", "braise", "no-cook"],
        "best_with": [],
        "pairs_with": ["broccoli", "onion", "potato"],
    },
]
