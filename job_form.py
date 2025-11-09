from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple

from playwright.sync_api import sync_playwright, Page
from google import genai
from google.genai import types
from google.genai.types import Content, Part

SCREEN_WIDTH = 1440
SCREEN_HEIGHT = 900
MODEL = "gemini-2.5-computer-use-preview-10-2025"
TURN_LIMIT = 10


def load_api_key() -> str:
    key_path = Path(__file__).with_name("gemini_api_key")
    if not key_path.exists():
        raise RuntimeError("Missing API key file 'gemini_api_key'.")
    key = key_path.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError("API key file is empty.")
    return key


def denorm_x(x: int) -> int:
    return int(x / 1000 * SCREEN_WIDTH)


def denorm_y(y: int) -> int:
    return int(y / 1000 * SCREEN_HEIGHT)


def ask_confirmation(safety_decision: Dict[str, Any]) -> bool:
    print("\n⚠ Confirmation required")
    print(safety_decision.get("explanation", ""))
    ans = input("Proceed? [y/N]: ").strip().lower()
    return ans.startswith("y")


def exec_calls(candidate, page: Page) -> List[Tuple[str, Dict[str, Any]]]:
    results: List[Tuple[str, Dict[str, Any]]] = []
    fcs = [p.function_call for p in candidate.content.parts if getattr(p, "function_call", None)]
    for fc in fcs:
        name = fc.name
        args = dict(fc.args or {})
        meta: Dict[str, Any] = {}
        if "safety_decision" in args:
            if not ask_confirmation(args["safety_decision"]):
                print("⛔ User denied action.")
                results.append((name, {"error": "user_denied"}))
                return results
            meta["safety_acknowledgement"] = True

        print(f"→ {name} {args}")
        try:
            if name == "open_web_browser":
                pass
            elif name == "navigate":
                page.goto(args["url"])
            elif name == "click_at":
                page.mouse.click(denorm_x(args["x"]), denorm_y(args["y"]))
            elif name == "type_text_at":
                x, y = denorm_x(args["x"]), denorm_y(args["y"])
                page.mouse.click(x, y)
                if args.get("clear_before_typing", True):
                    page.keyboard.press("Meta+A")
                    page.keyboard.press("Backspace")
                page.keyboard.type(args["text"])
                if args.get("press_enter", False):  # usually false for forms
                    page.keyboard.press("Enter")
            elif name == "scroll_document":
                direction = args.get("direction", "down").lower()
                if direction == "down":
                    page.keyboard.press("PageDown")
                elif direction == "up":
                    page.keyboard.press("PageUp")
            elif name == "key_combination":
                page.keyboard.press(args["keys"])  # e.g. "Tab" or "Enter"
            else:
                meta["warning"] = "unimplemented"
                print(f"⚠ Unimplemented action: {name}")

            try:
                page.wait_for_load_state(timeout=4000)
            except Exception:
                pass
            time.sleep(0.5)
            results.append((name, meta))
        except Exception as e:
            print(f"❌ Error {name}: {e}")
            results.append((name, {"error": str(e), **meta}))
    return results


def build_function_responses(page: Page, results: List[Tuple[str, Dict[str, Any]]]) -> List[types.FunctionResponse]:
    shot = page.screenshot(type="png")
    url = page.url
    frs: List[types.FunctionResponse] = []
    for name, payload in results:
        frs.append(
            types.FunctionResponse(
                name=name,
                response={"url": url, **payload},
                parts=[
                    types.FunctionResponsePart(
                        inline_data=types.FunctionResponseBlob(mime_type="image/png", data=shot)
                    )
                ],
            )
        )
    return frs


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python app1.py \"<goal describing how to fill form>\"")
        sys.exit(1)
    goal = " ".join(sys.argv[1:]).strip()
    api_key = load_api_key()
    client = genai.Client(api_key=api_key)

    html_path = Path(__file__).with_name("job_application.html").resolve()
    if not html_path.exists():
        raise RuntimeError("job_application.html not found.")
    file_url = f"file://{html_path}"
    print("📄 Form URL:", file_url)
    print("🎯 Goal:", goal)

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT})
    page = context.new_page()

    # If a local resume.pdf exists in the same folder, auto-attach it whenever
    # a file chooser opens (e.g., clicking the Resume input).
    resume_path = Path(__file__).with_name("resume.pdf").resolve()
    if resume_path.exists():
        def _on_filechooser(fc):
            try:
                fc.set_files(str(resume_path))
                print(f"📎 Attached file: {resume_path.name}")
            except Exception as e:
                print(f"❌ Failed to attach file: {e}")

        page.on("filechooser", _on_filechooser)
    else:
        print("No resume.pdf found next to app1.py. Skipping auto-attach.")

    try:
        page.goto(file_url)
        initial = page.screenshot(type="png")

        config = types.GenerateContentConfig(
            tools=[
                types.Tool(
                    computer_use=types.ComputerUse(environment=types.Environment.ENVIRONMENT_BROWSER)
                )
            ],
            thinking_config=types.ThinkingConfig(include_thoughts=True),
        )

        contents: List[Content] = [
            Content(
                role="user",
                parts=[Part(text=goal), Part.from_bytes(data=initial, mime_type="image/png")],
            )
        ]

        for turn in range(TURN_LIMIT):
            print(f"\n--- TURN {turn+1} ---")
            resp = client.models.generate_content(model=MODEL, contents=contents, config=config)
            cand = resp.candidates[0]
            contents.append(cand.content)

            if not any(getattr(p, "function_call", None) for p in cand.content.parts):
                final_text = " ".join(
                    [p.text for p in cand.content.parts if getattr(p, "text", None)]
                )
                print("✅ Final text:", final_text)
                break

            print("▶ Executing actions")
            results = exec_calls(cand, page)
            frs = build_function_responses(page, results)
            contents.append(Content(role="user", parts=[Part(function_response=fr) for fr in frs]))
        else:
            print("⏹ Reached turn limit.")
    finally:
        print("Closing browser…")
        browser.close()
        pw.stop()


if __name__ == "__main__":
    main()
