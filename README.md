# Sous Shelf - your personal cooking assistant

Sous Shelf is a chat agent that turns your available kitchen ingredients into high-protein, low added-fat meals. USDA provides access to nutrition data, allowing for each of the components to be calculated immediately.

Built onto **gemini-web-tool-calling**, deployed on Cloud Run

## Example prompts:

### 1. "I have chicken wings, broccoli, garlic powder, chili powder, and lemon juice."

Sous Shelf will add seasonings (garlic powder, chili powder, lemon juice) to pantry, then provide recipes using chicken wings and broccoli. It will also provide additional seasoning options for additional recipes.

*Utilizes update_pantry, suggest_from_pantry*

Picking one of the provided recipes will generate the full recipe, including ingredient portions, steps, nutrition data, and additional suggestions for improved flavor. Instead...

### 2. "Actually, I'd like to use shrimp instead of chicken wings. I also have paprika and tomatoes."

Sous Shelf will rethink and give options for recipes using shrimp, along with the other ingredients already existing on the user's shelf (and addition of paprika on the shelf). Another 3 options for recipes and additional seasoning options is provided.

Select any, which will provide a recipe. 

*Utilizes update_pantry, suggest_from_pantry, total_meal_macros*

Then give the third prompt:

### 3. "I've run out of lemon juice and garlic powder. Compare shrimp and chicken wings for nutrition."

The lemon juice and garlic powder will be removed from the pantry and no longer assumed available for future recipes. Then, Sous Shelf will give the nutritional value of shrimp and wings across 8 metrics.

*Utilizes update_pantry, get_nutrition*

## Tools Created - tools.py

### update_pantry (original; session state) 
Updates pantry when user mentions owning or running out of an ingredient

Arguments: **add**, **remove** - no arguments read the shelf
* All new sessions begin with salt and black pepper as assumed available
* Simplifies ingredient names ("pepper" -> black pepper, "limes" -> lime)
* Only adds seasonings, sauces, herbs, and oils; proteins and vegetables are treated as main ingredients to be used immediately

### suggest_from_pantry (original; follows local rules) 
Builds recipes from user's existing ingredients

Arguments: **protein**, **vegetables**, **method**, **servings**, **must_use**, **flavor_base**, **no_protein**, **max_added_fat_g**
* Picks from 16 existing flavor bases using what's available in the current session's pantry
* Open request: provides up to 4 recipes, described by name, taste, and seasoning; recipe steps aren't provided. If few ingredients are available, the cooking method is alternated instead
* When a recipe is chosen (**flavor_base**, **must_use**), a full recipe with specific measurements/amounts is provided
* Oil is capped at 4.5g of fat per serving
* Protein options are cooked using the preferred methods
* **could_unlock** provides up to two dishes that require an additional unmentioned ingredient
* **flavor_boosts** provides ideas for improving recipes
* **no_protein** creates a vegetable-only dish when the user specifies they do not have proteins or do not wish to use one

### get_nutrition (external; USDA FoodData Central) 
Answers questions about certain foods

* Arguments: **food**, **grams** (default to 100g), **target_protein_g**
* Searches lab-analyzed data sets (Foundation and SR Legacy), not specific brands of products
* **target_protein_g** returns weight of food needed to supply required protein amount (rounded to 5g)
* If a specific nutrient for an ingredient cannot be found on USDA, states "not reported" for said nutrient
* Can be used to compare food nutritional values 

### total_meal_macros (utilizes collected USDA data)
Calculates nutritional value of chosen recipes

* Arguments: **items** (food and per-serving weight), **servings**, **added_fat_g**, **protein_target_g**
* Conducts USDA lookups and adds up all ingredients used in a recipe
* Returns calories, protein, fat, carbs, saturated fat, sugars, fiber, and sodium, scaled to serving size of the dish
* **protein_target_g** raises main protein's weight until protein target is met (also applies additional protein through vegetables)

## Data Included

### pantry_rules.py
- 16 flavor bases, with required and optional ingredients, best preparation methods and pairing vegetables/spices
- 9 cooking methods (bake, air-fry, grill, braise, poach, steam, stir-fry, pan-sear, and no cook)
- 25 vegetables with cooking times
- 32 staple spices, sauces, oils the bot will suggest adding
- Flavor profiles for each seasoning to describe added effect
- Aliases for spelling and naming

### proteins.py
- 222 proteins with cooking profiles, types of protein, and USDA search term
- 57 cooking profiles including cut-specific times, temperatures, and preparation steps
- 120 aliases for spelling and naming
- Ruled to accept any food as protein, even if not included in 222 list, if USDA indicates at least 10g protein per 100g and 20% of calories from protein

## Agent (app.py)

### Model
- Up to 8 rounds of tool calls, then a final answer
- Each session maintains own message history and pantry in memory (**session_id**)
- System prompt sets the conversation rules and exact layout of the recipe options list and recipe card

### Conversation rules
- Uses only ingredients the user has listed
- Provides options for recipes unless the user names a dish
- Asks for protein if none is named, offers vegetable recipe as alternative
- Makes a no protein recipe only if the user refuses protein or requests a side, salad, or otherwise vegetable-centered dish
- Asks "Do you have ___" when providing recipe options for adding new options/flavor
- Appends each full recipe with additional ingredients for adding flavor
- Calls **suggest_from_pantry** and **total_meal_macros** for each recipe

### Guardrails
- Protein gate blocks no-protein dish that the user did not explicitly approve
- Pantry guard drops any item the user does not mention before creating recipe
- Options gate forces a list of options when the user asks for alternatives or additional ideas

### Typos or failures
- Fuzzy matching corrects typos (i.e. brocoli, papirka)
- USDA rate limit pauses lookups for a minute, bot says the numbers are unavailable
- Gemini is retried twice if busy, then responds with "try again in a minute" if failed

## Frontend (index.html, static/)
- Rustic look; yellowed, worn index cards for recipes and pantry; burlap cloth background texture
- Courier Prime for all text, Special Elite for titles
- Greets with "Hi! What do you have to cook with today?"
- Recipes are organized as a recipe card with Options, Ingredients, Steps, Nutrition per serving and To add more flavor sections
- Macro bar created from **total_meal_macros** data
- Tool trace under each reply shows every tool call with arguments and results
- Functions on desktop and mobile
- Four textures in **static/** were generated

## Deployment Files
* **Procfile** instructs Cloud Run to start **uvicorn app:app** on **$PORT**
* **.python-version** pins Python 3.13
* **pyproject.toml** and **uv.lock** dependencies
* **.env.example** shows **FDC_API_KEY**, real **.env** is git-ignored
On Cloud Run, **FDC_API_KEY** is set as environment variable
