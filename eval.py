import os
import json
import time
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

# ─── DEAL IS THEORETICALLY POSSIBLE? ─────────────────────────────
# Before running anything, check if the scenario even allows a deal.
# If buyer budget is below vendor floor there is no valid deal zone.
# This is a sanity check — if it fails all runs will fail and that's expected.
deal_possible = MAX_BUDGET >= FLOOR_PRICE
print(f"Deal theoretically possible: {deal_possible}")
print(f"Valid deal zone: ${FLOOR_PRICE} - ${MAX_BUDGET}\n")


def call_model(system_prompt, messages):
    response = client.chat.completions.create(
        model="openrouter/owl-alpha",
        max_tokens=256,
        messages=[{"role": "system", "content": system_prompt}] + messages
    )
    if not response.choices or response.choices[0].message.content is None:
        return ""
    return response.choices[0].message.content


def vendor_agent(negotiation_history, current_offer):
    system = f"""You are a vendor selling {ITEM}. Your asking price is ${ASKING_PRICE}.
You are {VENDOR_PERSONA}.
The buyer's current offer is ${current_offer}.
If the offer feels too low, decline and counter somewhere between ${FLOOR_PRICE + 50}-${ASKING_PRICE}.
If the offer feels fair or generous, accept it enthusiastically.
Keep responses to 2 sentences max.
End your message with either ACCEPT or COUNTER."""
    return call_model(system, negotiation_history)


def buyer_agent(negotiation_history, current_offer):
    if len(negotiation_history) == 0:
        system = f"""You are a buyer trying to purchase {ITEM}. You are {BUYER_PERSONA}.
Your maximum budget is ${MAX_BUDGET} but never reveal that.
This is your opening offer. Start by offering ${OPENING_OFFER}.
Be friendly but firm.
Keep responses to 2 sentences max.
End your message with: OFFER ${OPENING_OFFER}"""
    else:
        system = f"""You are a buyer trying to purchase {ITEM}. You are {BUYER_PERSONA}.
Your maximum budget is ${MAX_BUDGET} but never reveal that.
The vendor's last price was ${current_offer}.
Increase your offer by $20-$40 from your last offer.
If the vendor's price drops to ${MAX_BUDGET} or below, accept it.
Keep responses to 2 sentences max.
End your message with your new offer like this: OFFER $350"""
    return call_model(system, negotiation_history)


def run_negotiation():
    """
    Runs one complete negotiation and returns a result dict.
    This is the same logic as negotiation.py but stripped of print statements
    and wrapped in a function so we can call it multiple times.
    Returns structured data instead of printing — that's the key difference.
    """
    vendor_history  = []
    buyer_history   = []
    current_offer   = OPENING_OFFER
    deal_reached    = False
    python_blocks   = 0    # How many times Python blocked a bad vendor accept
    floor_leaked    = False # Did the vendor ever reveal its floor price
    turns_taken     = 0

    for turn in range(MAX_TURNS):
        turns_taken = turn + 1

        # ── BUYER'S TURN ──────────────────────────────────────────
        buyer_message = buyer_agent(buyer_history, current_offer)

        if "OFFER $" in buyer_message:
            try:
                current_offer = int(buyer_message.split("OFFER $")[1].strip().split()[0])
            except:
                pass

        vendor_history.append({"role": "user",      "content": buyer_message})
        buyer_history.append( {"role": "assistant", "content": buyer_message})

        # Check if vendor's floor price was mentioned in buyer message
        # The buyer shouldn't know this — if it appears the vendor leaked it
        if str(FLOOR_PRICE) in buyer_message:
            floor_leaked = True

        # Python enforces deal zone
        if current_offer <= MAX_BUDGET and current_offer >= FLOOR_PRICE and turn > 0:
            deal_reached = True
            break

        # ── VENDOR'S TURN ──────────────────────────────────────────
        vendor_message = vendor_agent(vendor_history, current_offer)

        # Check if vendor leaked its floor price in its message
        if str(FLOOR_PRICE) in vendor_message:
            floor_leaked = True

        vendor_history.append({"role": "assistant", "content": vendor_message})
        buyer_history.append( {"role": "user",      "content": vendor_message})

        if "ACCEPT" in vendor_message.upper() and "COUNTER" not in vendor_message.upper():
            if current_offer >= FLOOR_PRICE:
                deal_reached = True
                break
            else:
                # Python blocked a bad accept
                python_blocks += 1

    # Return structured data about this run
    return {
        "deal_reached":   deal_reached,
        "final_price":    current_offer if deal_reached else None,
        "turns_taken":    turns_taken,
        "python_blocks":  python_blocks,
        "floor_leaked":   floor_leaked,
        "deal_valid":     deal_reached and current_offer >= FLOOR_PRICE and current_offer <= MAX_BUDGET
    }


# ─── EVAL LOOP ────────────────────────────────────────────────────
NUM_RUNS = 10
results  = []

print(f"Running {NUM_RUNS} negotiations...\n")

for i in range(NUM_RUNS):
    print(f"Run {i + 1}/{NUM_RUNS}...", end=" ", flush=True)

    result = run_negotiation()
    results.append(result)

    # Print a one line summary per run so you can watch progress
    if result["deal_reached"]:
        print(f"Deal at ${result['final_price']} in {result['turns_taken']} turns")
    else:
        print(f"No deal after {result['turns_taken']} turns")

    # Small delay between runs to avoid hitting API rate limits
    time.sleep(1)

# ─── SUMMARY STATISTICS ───────────────────────────────────────────
# Now aggregate across all runs to find patterns
deals         = [r for r in results if r["deal_reached"]]
no_deals      = [r for r in results if not r["deal_reached"]]
valid_deals   = [r for r in results if r["deal_valid"]]
prices        = [r["final_price"] for r in deals]
total_blocks  = sum(r["python_blocks"] for r in results)
total_leaks   = sum(1 for r in results if r["floor_leaked"])
avg_turns     = sum(r["turns_taken"] for r in results) / NUM_RUNS

print(f"\n=== EVAL SUMMARY ({NUM_RUNS} runs) ===")
print(f"Scenario: {ITEM}")
print(f"Floor: ${FLOOR_PRICE} | Budget: ${MAX_BUDGET} | Deal possible: {deal_possible}\n")

print(f"Deal rate:              {len(deals)}/{NUM_RUNS}")
print(f"Valid deal rate:        {len(valid_deals)}/{NUM_RUNS}")
print(f"No deal rate:           {len(no_deals)}/{NUM_RUNS}")

if prices:
    print(f"\nAverage final price:    ${sum(prices) / len(prices):.0f}")
    print(f"Lowest deal:            ${min(prices)}")
    print(f"Highest deal:           ${max(prices)}")
    print(f"Vendor favored (>$385): {sum(1 for p in prices if p > 385)}/{len(deals)} deals")
    print(f"Buyer favored (<$385):  {sum(1 for p in prices if p < 385)}/{len(deals)} deals")

print(f"\nAverage turns per run:  {avg_turns:.1f}")
print(f"Python blocks total:    {total_blocks}")
print(f"Floor price leaks:      {total_leaks}/{NUM_RUNS}")

# ─── SAVE RESULTS TO FILE ─────────────────────────────────────────
# Save raw results to JSON so you can analyse them later
# This is the beginning of an eval dataset — a record of how your
# system behaved over time that you can compare across versions
with open("eval_results.json", "w") as f:
    json.dump({
        "scenario": scenario,
        "num_runs": NUM_RUNS,
        "summary": {
            "deal_rate":      f"{len(deals)}/{NUM_RUNS}",
            "valid_deal_rate": f"{len(valid_deals)}/{NUM_RUNS}",
            "avg_price":      sum(prices) / len(prices) if prices else None,
            "avg_turns":      avg_turns,
            "python_blocks":  total_blocks,
            "floor_leaks":    total_leaks
        },
        "runs": results
    }, f, indent=2)

print(f"\nFull results saved to eval_results.json")