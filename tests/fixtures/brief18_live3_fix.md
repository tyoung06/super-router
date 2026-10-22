A minimal FastAPI app is usually laid out as three files. This is a convention. Only the application code is strictly required.

1. **`main.py`** (required): creates the `FastAPI()` app object and defines one route, such as a GET on `/` that returns a JSON message.
2. **`requirements.txt`** (optional, conventional): lists the dependencies, `fastapi` and an ASGI server such as `uvicorn`.
3. **`README.md`** (optional, conventional): gives the command to run the app, for example `uvicorn main:app --reload` or `fastapi dev`.

The [official first-steps page](https://fastapi.tiangolo.com/tutorial/first-steps/) and [Real Python's guide](https://realpython.com/get-started-with-fastapi/) show the single-file app and the run commands. They don't cover `requirements.txt` or a README, so those two files are my own convention.

## Handoff
### Produced
Nothing written. The deliverable is the inline answer: a three-file FastAPI layout (`main.py`, `requirements.txt`, `README.md`) with a one-line description of each.

### Status
Handoff entries #1 and #2 are both "stopped: needs your label", and this task didn't touch them. The FastAPI file question is answered.

### Next
- Say whether you want `main.py` and `requirements.txt` scaffolded in the workspace.
- Supply the labels that #1 and #2 are waiting on.

Sources:
- https://fastapi.tiangolo.com/tutorial/first-steps/
- https://realpython.com/get-started-with-fastapi/