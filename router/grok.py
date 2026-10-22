"""Start a Grok Bot run through the router-inbox webhook."""
from router import safety, settings

TIMEOUT_SECONDS = 30


class DispatchError(safety.SafeError):
    """The webhook did not accept the task. The message never holds the URL or key."""


def build_payload(task_id, task):
    return {"task_id": task_id, "task": task}


def send(task_id, task, url, key, post):
    try:
        reply = post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json=build_payload(task_id, task),
            timeout=TIMEOUT_SECONDS,
        )
    except Exception as e:
        # Network errors often quote the host and path, so keep only the type.
        raise DispatchError(f"webhook request failed ({type(e).__name__})") from None
    if reply.status_code != 200:
        # The webhook's own error text says why (a rate limit, for example). It is server text,
        # so it is redacted and made safe to print by the caller like any other result.
        detail = ""
        try:
            body = reply.json()
            if isinstance(body, dict) and isinstance(body.get("error"), str) and body["error"].strip():
                detail = ": " + " ".join(body["error"].split())[:160]
        except Exception:
            pass
        raise DispatchError(f"webhook returned HTTP {reply.status_code}{detail}")
    try:
        body = reply.json()
    except ValueError:
        raise DispatchError("webhook reply was not JSON") from None
    if not isinstance(body, dict) or body.get("success") is not True or not body.get("runUuid"):
        raise DispatchError("webhook reply did not report success")
    return body["runUuid"]


# make_media (rules v2.10): Grok Imagine on the plan, at most 4 images, never video. Grok commits
# each image to the inbox repo and names the paths in its result; the router pulls only those.
IMAGE_CAP = 4
OUT_FOLDER = "media/out"


def imagine_instructions(task_id, repo=None):
    """Brief 24 (decision 11): the repo Grok commits to is the name part of `grok_inbox_repo` (`repo`, else the setting),
    so with the value the code used to spell, the sentence is byte for byte what it was. Unset, it reads `inbox`; a Grok
    call is never sent then (Grok Bot isn't set up), so no such prompt goes out."""
    found = repo or settings.inbox_repo()[0] or "inbox"
    name = found.split("/", 1)[-1]
    return (
        f"Make the image with Grok Imagine. At most {IMAGE_CAP} images. Images only: if the task asks for a video, "
        f"say so and make nothing. Commit each image to the {name} repository at "
        f"{OUT_FOLDER}/{task_id}/<short-name>.png, where <short-name> is a few plain words joined by dashes. "
        "Then return the result as usual, and list each committed path on its own line."
    )


def make_media_prompt(task_id, task_text):
    """The do call for make_media: the task, then how to make and commit the image."""
    return f"{task_text}\n\n{imagine_instructions(task_id)}"
