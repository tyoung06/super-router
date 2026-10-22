"""Build brief 11.1, phase A (rules v2.19, Checking): Grok's delivery cuts a long prompt at about 3,900 characters
(#55, #59), so the parts an agent must not lose come before the long blocks, for every agent. A fix prompt: the
instructions and the reply line, then TASK, REVIEW NOTES (and, on make_media, where to commit the image: the owner's
E1), then EARLIER RESULT, then the stage-before or pieces block. A check prompt (the owner's addition): the
instructions and the reply format, then TASK and RESULT. Every value here is fake."""
from router import checking, grok, split

TASK = "Write a long research brief about soil sensors."
LONG = "x" * 5000
NOTES = "1. Add the dates.\n2. Cite a source for the price.\n3. Remove the unsupported claim."
REPLY_LINE = "Reply with the complete revised result only, with no commentary about the changes."
FORMAT = "Reply format, with nothing before the first line:\nFirst line: exactly PASS or FIX.\nAfter FIX: a numbered list, one specific fix per line."


def _end_of(prompt, block):
    return prompt.index(block) + len(block)


# ---------- the fix prompt ----------

def test_a_grok_fix_prompt_from_a_5000_character_result_has_every_review_note_in_its_first_3000_characters():
    prompt = checking.fix_prompt(TASK, LONG, NOTES)
    notes = checking._block("REVIEW NOTES", NOTES)
    assert _end_of(prompt, notes) < 3000
    assert prompt.index(REPLY_LINE) < 3000


def test_the_fix_prompt_order_is_instructions_task_notes_then_the_earlier_result():
    prompt = checking.fix_prompt(TASK, LONG, NOTES)
    order = [prompt.index(REPLY_LINE), prompt.index("===== TASK ====="), prompt.index("===== REVIEW NOTES ====="),
             prompt.index("===== EARLIER RESULT =====")]
    assert order == sorted(order)
    assert prompt.endswith(checking._block("EARLIER RESULT", LONG))


def test_a_relay_fix_prompt_keeps_its_stage_before_block_last():
    prompt = checking.fix_prompt(TASK, LONG, NOTES, prior="THE NOTE", prior_label="RESEARCH NOTE")
    assert prompt.endswith(checking._block("RESEARCH NOTE", "THE NOTE"))
    assert prompt.index("===== REVIEW NOTES =====") < prompt.index("===== EARLIER RESULT =====") \
        < prompt.index("===== RESEARCH NOTE =====")
    assert checking.REPORT_FEWER_LINE in prompt


def test_a_split_fix_prompt_keeps_its_pieces_block_and_line():
    inputs = [{"text": "Piece one.", "result": "R1"}, {"text": "Piece two.", "result": "R2"}]
    prompt = checking.fix_prompt(TASK, LONG, NOTES, prior=split.pieces_text(inputs, "Join them."),
                                 prior_label=split.PIECES_LABEL, prior_lines=[split.FIX_LINE])
    assert prompt.endswith(split.pieces_block(inputs, "Join them."))
    assert split.FIX_LINE in prompt and prompt.index(split.FIX_LINE) < prompt.index("===== TASK =====")


def test_make_medias_commit_instructions_come_right_after_the_review_notes():
    imagine = grok.imagine_instructions("sr-x")
    prompt = checking.fix_prompt(TASK, LONG, NOTES, after_notes=imagine)
    assert _end_of(prompt, checking._block("REVIEW NOTES", NOTES)) < prompt.index(imagine) \
        < prompt.index("===== EARLIER RESULT =====")
    assert _end_of(prompt, imagine) < 3000


# ---------- the check prompt (the owner's addition) ----------

def test_a_check_prompt_for_a_5000_character_result_has_its_reply_format_in_its_first_3000_characters():
    for kw in ({"no_tools": True}, {"no_tools": False, "can_browse": True}, {"no_tools": False, "relay": True}):
        prompt = checking.checker_prompt(TASK, LONG, **kw)
        assert _end_of(prompt, FORMAT) < 3000, kw
        assert prompt.endswith(checking._block("RESULT", LONG))


def test_the_check_prompt_order_is_instructions_format_then_task_and_result():
    prompt = checking.checker_prompt(TASK, LONG, no_tools=True, relay=True)
    order = [prompt.index(checking.NO_RESULT_RULE), prompt.index(checking.NO_NEW_RESEARCH_LINE),
             prompt.index(checking.NO_TOOLS_PARAGRAPH), prompt.index(FORMAT), prompt.index("===== TASK ====="),
             prompt.index("===== RESULT =====")]
    assert order == sorted(order)
