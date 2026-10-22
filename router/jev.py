"""Ask Jev (TypeSafe) which skill a task needs. One request per task.

Jev sees only the task text, the skill descriptions (with their not_for lines) and two
questions. The key is read from .env by the caller and passed in; it is never printed,
logged, or put in os.environ. option_value, build_criteria and ask_jev are copied from
labeltest/jev_client.py, which stays as the record of the two label tests.
"""
import random

from typesafe_sdk import Choice, Noul, RetryPolicy, TypeSafeClient

# The SDK's own default address, passed on purpose, so a TYPESAFE_BASE_URL in the shell
# can't send the key anywhere else.
BASE_URL = "https://api.typesafe.ai"
# SUPER-ROUTER.md, Money: Jev stops being called after this many input tokens in a
# calendar month (UTC), counted from the log.
MONTHLY_TOKEN_CAP = 1_000_000
# One request per task. The SDK would otherwise retry up to twice, and a retried request
# could be billed without its tokens reaching the log.
NO_RETRIES = RetryPolicy(max_retries=0)


class KeyMissing(Exception):
    """JEV_API_KEY is missing or empty in .env. Since build brief 24 (decision 13) `label` answers `not_set_up` instead of
    raising it; the class stays for anything that still catches it."""


class UnknownLabel(Exception):
    """Jev answered with a label that is not in the skill table."""


def make_client(api_key):
    return TypeSafeClient(api_key=api_key, base_url=BASE_URL, retry=NO_RETRIES)


def option_value(skill):
    """The description string, or {"what", "not_for"} when the skill has a not_for line."""
    if skill.get("not_for"):
        return {"what": skill["description"], "not_for": skill["not_for"]}
    return skill["description"]


def build_criteria(table, seed):
    """Skill key -> option value, plus the fallback, in an order shuffled by seed."""
    lab = table["labeler"]
    items = [(k, option_value(v)) for k, v in table["skills"].items()]
    items.append((lab["fallback_label"], lab["fallback_description"]))
    random.Random(seed).shuffle(items)
    return dict(items)


def ask_jev(task_text, *, seed, table, client):
    """One Jev call: the skill question and the needs_split question together."""
    lab = table["labeler"]
    questions = {
        "skill": Choice(instructions=lab["question"], criteria=build_criteria(table, seed)),
        "needs_split": Noul(instructions=lab["second_question"]["instructions"]),
    }
    response = client.system_one(state=task_text, questions=questions, model=lab["jev_model"])
    skill = response.answers["skill"]
    return {
        "choice": skill.choice,
        "confidence": skill.confidence,
        "probabilities": dict(skill.probabilities),
        "noul": response.answers["needs_split"].noul,
        "input_tokens": response.usage.input_tokens or 0,
    }


def label(task_text, *, task_id, roster, api_key, tokens_this_month, make_client=make_client):
    """Label one task. Returns what log.add_task stores: status, label, confidence,
    needs_split, tokens, error. The option order is shuffled with the task_id as the seed,
    so it can be rebuilt from the log. Never raises for a Jev problem; an error is stored as
    its type name only, because SDK messages can quote addresses and server text.

    Status, first match wins: not_set_up, over_cap, error, below_floor, none_of_these, ok. Build brief 24 (decision 13):
    with no JEV_API_KEY, Jev isn't called at all (`not_set_up`, 0 tokens): the task asks for its skill, as on an error."""
    if not (api_key or "").strip():
        return {"status": "not_set_up", "tokens": 0}
    if tokens_this_month >= MONTHLY_TOKEN_CAP:
        return {"status": "over_cap"}
    lab = roster.labeler
    tokens = 0
    try:
        if not (api_key or "").strip():
            raise KeyMissing()
        client = make_client(api_key)
        try:
            answer = ask_jev(task_text, seed=task_id, table=roster.table, client=client)
        finally:
            client.close()
        tokens = int(answer["input_tokens"])
        choice, confidence = answer["choice"], float(answer["confidence"])
        if choice not in roster.skills and choice != lab["fallback_label"]:
            raise UnknownLabel()
    except Exception as e:
        return {"status": "error", "error": type(e).__name__, "tokens": tokens}
    if confidence < lab["min_confidence"]:
        status = "below_floor"
    elif choice == lab["fallback_label"]:
        status = "none_of_these"
    else:
        status = "ok"
    needs_split = answer["noul"] if isinstance(answer["noul"], (int, float)) else None
    return {"status": status, "label": choice, "confidence": confidence, "needs_split": needs_split,
            "tokens": tokens}
