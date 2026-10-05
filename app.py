import difflib
import json
import os
import re
import uuid
from pathlib import Path

import litellm
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pantry_rules import ALIASES, DEFAULT_PANTRY, METHOD_ALIASES, METHOD_COOKING_OIL_TSP
from tools import FLAVOR_ITEMS, TOOLS, _as_list, _clean, run_tool

# --- Config ---

SYSTEM_PROMPT = """\
You are Sous Shelf, a cooking assistant for a home cook who wants high-protein, \
low-added-fat meals made only from what they have in their kitchen. You can also make a vegetable \
dish or a side with no protein when that is what they ask for.

The page has already greeted the user and asked what they have to cook with, so a first message \
that only lists ingredients is a request for a recipe using them. The greeting is done: never open \
a reply with "Hi", "Hello" or any other greeting. Start with the answer or the question itself.

What the user has
- The pantry starts with only salt and black pepper. Assume the user has told you everything they \
have. Never use or mention an ingredient they have not named, other than salt and black pepper.
- When the user names seasonings, spices, sauces, oils, vinegars, sweeteners, citrus, garlic or ginger, \
call update_pantry to add them before anything else. List each one separately: "onion and garlic \
powder" means onion powder and garlic powder.
- The protein, fresh vegetables, rice and potatoes are not pantry items. Pass them to suggest_from_pantry.
- When the user says they ran out of something, call update_pantry to remove it, then call \
suggest_from_pantry again if a recipe is in progress.
- Asking whether the user has an ingredient happens only while they are still choosing. When the \
tool returns options and could_unlock has entries, put one line per entry after the options, such as \
"Do you have cumin? With it I could also make a cumin-chili rub." Then ask which option they would like.
- Once a full recipe is given, never ask whether they have an ingredient. If the result has \
flavor_boosts, end the reply with a short section headed "To add more flavor" that lists every idea \
and what it would add, as suggestions. Never put these extras in the recipe itself.
- If the user says they do have something you asked about or suggested, add it with update_pantry and \
call suggest_from_pantry again.
- Do not steer the user toward any particular ingredient or cuisine. Offer only what the tool returns.

Protein
- Any meat, poultry, fish, shellfish, egg, tofu, bean or lentil is a protein: chicken thighs, pork ribs, \
salmon, shrimp, eggs, black beans and so on. When the user names one, even with nothing else ("I have \
chicken thighs"), that is all you need: call suggest_from_pantry with it straight away. Never ask \
which protein they have when they have just told you.
- Vegetables, rice and potatoes are not proteins.
- A main dish is built around one protein that the user has named. If they have not named one, do not \
give a recipe and never pick a protein for them. Reply with one short question asking which protein \
they have, say that a vegetable dish with no protein is also possible, and invite them to list any \
seasonings or sauces too. Remember the vegetables and sides they named for when they answer.
- A message that only lists vegetables is not a request for a dish without protein. Ask first.
- Do not ask for a protein, and do not ask twice, when the user has said they do not want or do not \
have one, or has asked outright for a side dish, a vegetable dish or a meatless dish. Call \
suggest_from_pantry with no_protein set to true and their vegetables and sides, and give that recipe.
- For a dish with no protein, pass each vegetable to total_meal_macros at about 150 g per serving.

Recipes
- Always call suggest_from_pantry before giving a recipe, and pass the number of servings. Never write \
a recipe, or a list of options, from memory.
- It answers in one of two ways. If the result has "options", the user has not chosen a dish yet: \
list every option and ask which one they want. Give no steps and no nutrition, and do not call \
total_meal_macros. If the result has "recipes", give that one recipe in full.
- Whenever the user asks for a recipe without saying which dish or flavor they want, and whenever they \
ask for alternatives or other ideas, call it without flavor_base so they get the options.
- When the user picks an option, by number, name or description, call it again with flavor_base and \
method set to that option. Otherwise set method only when the user named a way of cooking. Keep the same flavor_base when they later change an ingredient, the \
protein or the servings.
- When the user asks for a dish by style or flavor (BBQ ribs, lemon-garlic chicken, a honey-mustard \
glaze), pass the ingredient that style depends on as must_use, for example "bbq sauce" for BBQ. If \
the tool says it is not in the pantry, ask the user whether they have it before giving any recipe.
- Use only the seasoning and oil the tool returns; never add ingredients that are not in its result. \
Its amounts are already totals for all servings. Copy them as they are.
- After a full recipe, name the other flavors possible in one line, if there are any.
- Reuse the protein, vegetables and servings from earlier in the conversation unless the user changes them.
- Only use vegetables and sides the user has named. If they named none, make the recipe without them.

Nutrition
- Every nutrition number must come from a tool. Never estimate, recall, add or multiply nutrition numbers.
- For a recipe, call total_meal_macros right after suggest_from_pantry. Pass the protein first and then \
each vegetable, with the weight for ONE serving, plus the servings, the recipe's added_fat_g_per_serving, \
and protein_target_g if the user asked for a protein amount. It looks up USDA itself, so do not call \
get_nutrition for recipe ingredients.
- Report its per_serving totals as they are, and list each ingredient's grams_for_all_servings.
- For a question about one food, call get_nutrition.
- To compare foods, call get_nutrition for each one at the same weight and show the figures side by \
side. You may say which is higher or lower on each figure. Do not give an overall score or ranking.
- If a tool returns an error, say the number is unavailable. Do not guess.
- Seasonings and sauces are not counted in the totals. Say so in one short line.

Tool errors
- When a tool returns an error, do what its suggestion says. Never repeat a call with the same arguments.

Final answer
- Answer every part of the request, using all the tool results from this turn, not only the last one.
- The page shows your answer on a recipe card and looks for these exact layouts.
- Options: the heading "Options", then one line per option numbered "1." "2." and so on, each with \
the option's name, a colon, what it tastes like, and its seasoning in brackets. Then a blank line and \
one question asking which they would like.
- A recipe:
  line 1: the recipe name, exactly as the tool gave it
  line 2: Serves N
  a blank line, then the heading "Ingredients" and one ingredient per line starting with "- ", with \
amounts for all servings
  a blank line, then the heading "Steps" and the steps numbered "1." "2." and so on
  a blank line, then the heading "Nutrition per serving" and one figure per line starting with "- ": \
calories, protein, fat, saturated fat, carbs, sugars, fiber, sodium
  then one line saying seasonings are not counted in the totals
- Flavor ideas go under the heading "To add more flavor", one per line starting with "- ".
- Write headings on their own line with nothing else on it.

Style
- Plain text only: no markdown symbols, no tables. Short lines. Give weights in grams.
- Use everyday ingredient names (chicken thigh, zucchini), not the USDA search names.
- Keep USDA entry names out of the ingredient list. Mention one only if the user asks where a number came from.
- You report food data and recipes. Do not give medical or diet-plan advice.
- Food recalls and safety alerts are outside what you can check. If the user asks about them, \
tell them in your own words that you cannot check recalls and that the FDA and USDA publish them.
"""
NUDGE = "(Carry on: call the next tool you need, or answer my last message.)"
MODEL = "vertex_ai/gemini-3.5-flash-lite"
MAX_TOOL_ROUNDS = 8

# --- The Harness ---

# The model is quick to drop the protein when the user only lists vegetables. So the harness, not the
# model, decides when a dish may go without one: the user has to have said so. These are the phrases
# that count when they appear in the user's own message.
NO_PROTEIN_REQUEST = re.compile(
    r"\b(no|without|skip|skip the|hold the)\s+(protein|meat)\b"
    r"|\b(don'?t|do not)\s+(want|need|have)\s+(a |any )?(protein|meat)\b"
    r"|\bsides?\b|\bside dish(es)?\b|\bsalad\b|\bmeatless\b"
    r"|\bvegetable (dish|stir[- ]?fry|side|medley)\b|\b(veg|veggie|vegetable)s?[- ]only\b"
    r"|\b(just|only) (the )?(veg|veggies|vegetables)\b",
    re.IGNORECASE,
)

# What the model is told when it tries to skip the protein without the user having asked for that.
ASK_FOR_PROTEIN_FIRST = json.dumps({
    "error": "the user has not said they want a dish without protein",
    "suggestion": "Do not set no_protein and do not give a recipe yet. Ask the user which protein they have, "
    "and mention that they can also ask for a vegetable dish with no protein.",
})


# The model also likes to help itself to ingredients: ask for "bbq ribs" and it may add bbq sauce to
# the pantry unasked. So an item only goes on the shelf if the user typed it, or Sous Shelf asked about it
# in its last reply and the user is answering.
NOT_SAID = "The user has not said they have these, so they were left out. Do not assume them: ask the user whether they have them."


def said_by_user(item: str, heard: str) -> bool:
    """Has this pantry item come up in what the user typed, or in the question they are answering?

    Typos count ("paprka" is paprika), and so do the other names in ALIASES ("soy" is soy sauce).
    """
    heard = heard.lower()
    if any(target == item and re.search(rf"\b{re.escape(alias)}\b", heard) for alias, target in ALIASES.items()):
        return True
    words = re.findall(r"[a-z]+", heard)
    return all(difflib.get_close_matches(word, words, n=1, cutoff=0.85) for word in re.findall(r"[a-z]+", item))


# When the user asks what else they could make, they want the list again, not one more recipe.
OPTIONS_REQUEST = re.compile(
    r"\b(alternatives?|any other|what else|something (else|different)|what are my options"
    r"|(other|more|different) (options|recipes|ideas|dishes|choices)|another (recipe|option|idea|dish)"
    r"|(give|show) me (some |the |my )?options)\b",
    re.IGNORECASE,
)


def flavor_section(boosts: dict) -> str:
    """The "To add more flavor" part of a reply, written from the tool's own suggestions."""
    lines = ["To add more flavor"]
    lines += ["- " + idea for idea in boosts.get("seasonings_for_this_recipe", [])]
    if boosts.get("vegetables_and_sides_that_suit_it"):
        lines += ["- vegetables and sides that suit it: " + ", ".join(boosts["vegetables_and_sides_that_suit_it"])]
    return "\n".join(lines)


# "Do you have cumin?" belongs with the options, before a dish is chosen. After a full recipe it is removed.
HAVE_QUESTION = re.compile(r"^[^\n]*\bdo you (happen to )?have\b[^\n]*\?[^\n]*\n?", re.IGNORECASE | re.MULTILINE)


def run_agent(session: dict, may_skip_protein: bool) -> tuple[str, list[dict]]:
    """Complete until the model answers without asking for a tool.

    Returns the final text and a record of every tool call made along the way.
    The pantry belongs to the session; tools that need it get it from here, not from the model.
    may_skip_protein says whether the user has agreed to a dish with no protein.
    """
    messages, pantry = session["messages"], session["pantry"]
    tool_calls = []

    # What the user has typed in this session, plus Sous Shelf's last reply (they may be answering it).
    typed = [m["content"] for m in messages if m["role"] == "user" and m["content"] != NUDGE]
    last_reply = next((m["content"] for m in reversed(messages[:-1]) if m["role"] == "assistant" and m.get("content")), "")
    heard = " ".join(typed + [last_reply])
    wants_options = bool(OPTIONS_REQUEST.search(typed[-1]))

    for _ in range(MAX_TOOL_ROUNDS):
        reply = litellm.completion(
            model=MODEL,
            vertex_location="global",
            messages=messages,
            tools=TOOLS,
            num_retries=2,  # wait and try again if Gemini says it is busy
        ).choices[0].message

        # Append assistant's reply (text, tool calls, or both) to the context.
        # model_dump() keeps it a plain dict: the raw object carries provider-specific
        # fields that trip Pydantic when LiteLLM re-serializes it next round.
        messages += [reply.model_dump()]

        if not reply.tool_calls:
            if reply.content:
                return reply.content, tool_calls
            # Gemini now and then returns an empty turn, most often right after a pantry update.
            # Drop it and nudge the model to carry on.
            messages.pop()
            messages += [{"role": "user", "content": NUDGE}]
            continue

        # The harness, not the model, runs each tool and appends the result
        for call in reply.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            name = call.function.name

            # Leave out anything the model wants on the shelf that the user never mentioned.
            assumed = []
            if name == "update_pantry":
                assumed = [item for item in _as_list(args.get("add")) if not said_by_user(_clean(item), heard)]
                args["add"] = [item for item in _as_list(args.get("add")) if item not in assumed]
            elif name == "suggest_from_pantry":
                # Seasonings sometimes arrive in the vegetables list. They get the same check.
                listed = _as_list(args.get("vegetables"))
                assumed = [item for item in listed if _clean(item) in FLAVOR_ITEMS and not said_by_user(_clean(item), heard)]
                args["vegetables"] = [item for item in listed if item not in assumed]
                if wants_options:
                    # "What else could I make?" gets the list again, even if the model picked a dish.
                    args.pop("flavor_base", None)
                    named = [m for m in [*METHOD_COOKING_OIL_TSP, *METHOD_ALIASES] if re.search(rf"\b{re.escape(m)}\b", typed[-1].lower())]
                    if not named:
                        args.pop("method", None)

            skipping_protein = name == "suggest_from_pantry" and args.get("no_protein") and not args.get("protein")
            if skipping_protein and not may_skip_protein:
                result = ASK_FOR_PROTEIN_FIRST
            else:
                result = run_tool(name, args, pantry)
                if skipping_protein:
                    # The user chose a dish without protein. Remember it, so follow-ups are not asked again.
                    session["meatless_ok"] = True
            if assumed:
                result = json.dumps({**json.loads(result), "left_out": assumed, "why": NOT_SAID}, ensure_ascii=False)
            tool_calls += [{"name": name, "args": args, "result": result}]

            messages += [{"role": "tool", "tool_call_id": call.id, "content": result}]

    # Out of rounds. Ask once more with tools switched off, so the user still gets an answer
    # built from what the tools already returned.
    reply = litellm.completion(
        model=MODEL,
        vertex_location="global",
        messages=messages,
        tools=TOOLS,
        tool_choice="none",
        num_retries=2,
    ).choices[0].message
    messages += [reply.model_dump()]
    return reply.content or "Sorry, I hit my tool-call limit before finishing.", tool_calls


# --- Session Store ---

# session_id -> {"messages": [...], "pantry": [...], ...}. In-memory, single process.
sessions: dict[str, dict] = {}


def new_session() -> dict:
    """Every session gets its own history and its own copy of the default pantry."""
    return {
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
        "pantry": list(DEFAULT_PANTRY),
        # True once Sous Shelf has asked which protein the user has, until their next message answers it.
        "asked_for_protein": False,
        # True once the user has chosen a dish with no protein in this session.
        "meatless_ok": False,
    }


# --- FastAPI App ---

app = FastAPI()

# The page's paper and cloth textures.
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[dict]


@app.get("/")
def index():
    # no-cache makes the browser check for a newer page on every visit instead of showing a stale copy.
    return FileResponse(Path(__file__).parent / "index.html", headers={"Cache-Control": "no-cache"})


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    # Get or create the session
    session_id = request.session_id or str(uuid.uuid4())
    if session_id not in sessions:
        sessions[session_id] = new_session()
    session = sessions[session_id]

    # Append user's message to the context
    session["messages"] += [{"role": "user", "content": request.message}]

    # A dish may go without protein only if the user asked for that: in this message, earlier in the
    # session, or by answering Sous Shelf's "which protein do you have?" with something other than a protein.
    answering = session["asked_for_protein"]
    may_skip_protein = session["meatless_ok"] or answering or bool(NO_PROTEIN_REQUEST.search(request.message))

    try:
        response, tool_calls = run_agent(session, may_skip_protein)
    except litellm.RateLimitError:
        # Gemini is turning requests away for the moment. Say so plainly instead of showing the raw error.
        response, tool_calls = "Gemini is busy right now and turned this request away. Please wait a minute and send it again.", []
    except Exception as e:
        # Auth, billing, a model that is not running: show it in the chat, not as a 500.
        response, tool_calls = f"Model call failed: {type(e).__name__}: {str(e)[:300]}", []

    # Tidy the reply around what the recipe tool last returned, and keep the chat history in step.
    for call in reversed(tool_calls):
        result = json.loads(call["result"]) if call["name"] == "suggest_from_pantry" else {}
        if "recipes" in result:
            # A full recipe: no "do you have ...?" questions, and it ends with ideas for improving it.
            response = HAVE_QUESTION.sub("", response).rstrip()
            if result.get("flavor_boosts") and "to add more flavor" not in response.lower():
                response += "\n\n" + flavor_section(result["flavor_boosts"])
        elif "options" in result:
            # Still choosing: this is where ingredients are asked about, if the model forgot to.
            for extra in result.get("could_unlock", []):
                if extra["ask_user_if_they_have"].split(" or ")[0] not in response.lower():
                    response = response.rstrip() + f"\n\nDo you have {extra['ask_user_if_they_have']}? With it I could also make {extra['flavor_base'].lower()}."
        else:
            continue
        session["messages"][-1]["content"] = response
        break

    # Did this reply ask for a protein instead of giving a recipe? Then the next message is the answer.
    gave_recipe = any('"recipes"' in call["result"] or '"options"' in call["result"] for call in tool_calls)
    session["asked_for_protein"] = not gave_recipe and "protein" in response.lower() and "?" in response

    return ChatResponse(response=response, session_id=session_id, tool_calls=tool_calls)


@app.get("/pantry")
def pantry(session_id: str | None = None):
    """The shelf for the sidebar: this session's pantry, or the default one before the first message."""
    session = sessions.get(session_id)
    return {"pantry": session["pantry"] if session else DEFAULT_PANTRY}


@app.post("/clear")
def clear(session_id: str | None = None):
    sessions.pop(session_id, None)
    return {"status": "ok"}


if __name__ == "__main__":
    # Cloud Run sets PORT and needs the app reachable from outside the container.
    # On a laptop there is no PORT, so it stays private on localhost:8000.
    on_cloud_run = "PORT" in os.environ
    uvicorn.run(app, host="0.0.0.0" if on_cloud_run else "127.0.0.1", port=int(os.environ.get("PORT", 8000)))
