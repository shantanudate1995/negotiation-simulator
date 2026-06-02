import os
import json
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env
load_dotenv()

# Create the API client pointing to OpenRouter
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

# ─── LOAD SCENARIO CONFIG ─────────────────────────────────────────
# All scenario details live in scenario.json.
# The code never needs to change when the scenario changes.
# This is separation of concerns — logic in code, data in config.
with open("scenario.json") as f:
    scenario = json.load(f)

ITEM           = scenario["item"]
ASKING_PRICE   = scenario["vendor"]["asking_price"]
FLOOR_PRICE    = scenario["vendor"]["floor_price"]
VENDOR_PERSONA = scenario["vendor"]["personality"]
OPENING_OFFER  = scenario["buyer"]["opening_offer"]
MAX_BUDGET     = scenario["buyer"]["max_budget"]
BUYER_PERSONA  = scenario["buyer"]["personality"]
MAX_TURNS      = scenario["max_turns"]


def call_model(system_prompt, messages):
    """
    Single reusable function to call the AI model.
    All three agents use this — vendor, buyer, and judge.
    Guards against empty responses — models fail sometimes.
    """
    response = client.chat.completions.create(
        model="openrouter/owl-alpha",
        max_tokens=256,
        messages=[{"role": "system", "content": system_prompt}] + messages
    )
    # Guard against empty responses from the model
    if not response.choices or response.choices[0].message.content is None:
        return ""
    return response.choices[0].message.content


def vendor_agent(negotiation_history, current_offer):
    """
    The vendor agent generates natural negotiation dialogue.
    Its ONLY job is language — sounding like a real vendor.
    Python enforces the floor price, not this function.
    """
    system = f"""You are a vendor selling {ITEM}. Your asking price is ${ASKING_PRICE}.
You are {VENDOR_PERSONA}.
The buyer's current offer is ${current_offer}.
If the offer feels too low, decline and counter somewhere between ${FLOOR_PRICE + 50}-${ASKING_PRICE}.
If the offer feels fair or generous, accept it enthusiastically.
Keep responses to 2 sentences max.
End your message with either ACCEPT or COUNTER."""
    return call_model(system, negotiation_history)


def buyer_agent(negotiation_history, current_offer):
    """
    The buyer agent generates natural negotiation dialogue.
    Its ONLY job is language — sounding like a real buyer.
    Python enforces the budget constraint, not this function.
    """
    if len(negotiation_history) == 0:
        # First turn — no history yet, give explicit opening instructions
        system = f"""You are a buyer trying to purchase {ITEM}. You are {BUYER_PERSONA}.
Your maximum budget is ${MAX_BUDGET} but never reveal that.
This is your opening offer. Start by offering ${OPENING_OFFER}.
Be friendly but firm.
Keep responses to 2 sentences max.
End your message with: OFFER ${OPENING_OFFER}"""
    else:
        # Subsequent turns — respond to the vendor's last price
        system = f"""You are a buyer trying to purchase {ITEM}. You are {BUYER_PERSONA}.
Your maximum budget is ${MAX_BUDGET} but never reveal that.
The vendor's last price was ${current_offer}.
Increase your offer by $20-$40 from your last offer.
If the vendor's price drops to ${MAX_BUDGET} or below, accept it.
Keep responses to 2 sentences max.
End your message with your new offer like this: OFFER $350"""
    return call_model(system, negotiation_history)


def judge_agent(final_offer, deal_reached):
    """
    The judge evaluates the outcome against both parties constraints.
    Key design decision: ALL booleans are calculated in Python.
    The model ONLY writes the reasoning sentence.
    This prevents the model from lying about constraint violations —
    which we saw it do when we let it write the booleans itself.
    """
    system = """You are a deal evaluator. Respond with ONLY a JSON object, nothing else."""

    # Python calculates all facts — model cannot override these
    within_budget = final_offer <= MAX_BUDGET
    above_floor   = final_offer >= FLOOR_PRICE
    deal_valid    = deal_reached and within_budget and above_floor

    # We pre-fill every boolean and number in the JSON template.
    # The model only fills in the reasoning sentence.
    prompt = f"""A negotiation for {ITEM} just ended.
Final price: ${final_offer}
Deal reached: {deal_reached}
Vendor floor: ${FLOOR_PRICE}
Buyer budget: ${MAX_BUDGET}

Write ONE sentence explaining how the negotiation went.
Respond with ONLY this JSON and nothing else:
{{"deal_reached": {str(deal_reached).lower()}, "final_price": {final_offer}, "within_buyer_budget": {str(within_budget).lower()}, "above_vendor_floor": {str(above_floor).lower()}, "deal_valid": {str(deal_valid).lower()}, "reasoning": "YOUR ONE SENTENCE HERE"}}"""

    response = call_model(system, [{"role": "user", "content": prompt}])
    return response


# ─── NEGOTIATION LOOP ─────────────────────────────────────────────
vendor_history = []            # Vendor's view of the conversation
buyer_history  = []            # Buyer's view of the conversation
current_offer  = OPENING_OFFER # Tracks the current offer on the table
deal_reached   = False         # Did we end with a valid deal?

print(f"=== NEGOTIATION START ===")
print(f"Item: {ITEM}")
print(f"Asking: ${ASKING_PRICE} | Floor: ${FLOOR_PRICE} | Buyer budget: ${MAX_BUDGET}\n")

for turn in range(MAX_TURNS):

    # ── BUYER'S TURN ──────────────────────────────────────────────
    buyer_message = buyer_agent(buyer_history, current_offer)
    print(f"BUYER:  {buyer_message}\n")

    # Extract the dollar amount from OFFER $XXX
    # We told the buyer to always end with OFFER $XXX for reliable parsing
    if "OFFER $" in buyer_message:
        try:
            current_offer = int(buyer_message.split("OFFER $")[1].strip().split()[0])
        except:
            pass  # If parsing fails keep the last known offer

    # Update both histories from each agent's own perspective
    vendor_history.append({"role": "user",      "content": buyer_message})
    buyer_history.append( {"role": "assistant", "content": buyer_message})

    # ── PYTHON ENFORCES DEAL ZONE ─────────────────────────────────
    # Only force acceptance if the offer satisfies BOTH parties:
    # within buyer's budget AND at or above vendor's floor price.
    # A deal below the vendor's floor is not a real deal.
    # We skip turn 0 so the buyer always makes at least one offer first.
    if current_offer <= MAX_BUDGET and current_offer >= FLOOR_PRICE and turn > 0:
        print(f">>> PYTHON: Offer ${current_offer} satisfies both parties. Forcing acceptance.\n")
        deal_reached = True
        break

    # ── VENDOR'S TURN ─────────────────────────────────────────────
    vendor_message = vendor_agent(vendor_history, current_offer)
    print(f"VENDOR: {vendor_message}\n")
    print(f"--- Turn {turn + 1} of {MAX_TURNS} ---\n")

    # Update histories from each agent's perspective
    vendor_history.append({"role": "assistant", "content": vendor_message})
    buyer_history.append( {"role": "user",      "content": vendor_message})

    # ── PYTHON ENFORCES VENDOR FLOOR PRICE ────────────────────────
    # If the model said ACCEPT but the offer is below the floor,
    # Python blocks it — the vendor cannot legally accept below floor.
    # If the offer is at or above floor and model said ACCEPT, honor it.
    if "ACCEPT" in vendor_message.upper() and "COUNTER" not in vendor_message.upper():
        if current_offer >= FLOOR_PRICE:
            # Legitimate acceptance — price is at or above floor
            print(f">>> VENDOR ACCEPTED at ${current_offer} (above floor ${FLOOR_PRICE})\n")
            deal_reached = True
            break
        else:
            # Model tried to accept below floor — Python blocks it
            print(f">>> PYTHON: Blocked vendor from accepting ${current_offer} below floor ${FLOOR_PRICE}. Forcing counter.\n")

# ── JUDGE EVALUATION ──────────────────────────────────────────────
# Negotiation is over — call the judge to evaluate the outcome
print("\n=== JUDGE EVALUATION ===\n")

raw_verdict = judge_agent(current_offer, deal_reached)
print(f"Raw judge response:\n{raw_verdict}\n")

# Parse the JSON verdict — strip markdown fences if model added them
try:
    clean   = raw_verdict.strip().replace("```json", "").replace("```", "").strip()
    verdict = json.loads(clean)

    print("=== VERDICT ===")
    print(f"Deal reached:        {verdict['deal_reached']}")
    print(f"Final price:         ${verdict['final_price']}")
    print(f"Within buyer budget: {verdict['within_buyer_budget']}")
    print(f"Above vendor floor:  {verdict['above_vendor_floor']}")
    print(f"Deal valid:          {verdict['deal_valid']}")
    print(f"Reasoning:           {verdict['reasoning']}")

except json.JSONDecodeError:
    # Model didn't return valid JSON despite instructions — real failure mode
    print("ERROR: Judge did not return valid JSON. Raw response above.")