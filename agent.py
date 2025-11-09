from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from termcolor import cprint
from playwright.sync_api import sync_playwright, Page

from google import genai
from google.genai import types
from google.genai.types import Content, Part


# --- Constants and utilities ---
SCREEN_WIDTH = 1440
SCREEN_HEIGHT = 900
MODEL = "gemini-2.5-computer-use-preview-10-2025"


def denorm_x(x: int) -> int:
    return int(x / 1000 * SCREEN_WIDTH)


def denorm_y(y: int) -> int:
    return int(y / 1000 * SCREEN_HEIGHT)


def ask_confirmation(safety_decision: Dict[str, Any]) -> bool:
    cprint("\n⚠ Safety check: confirmation required", "yellow")
    print(safety_decision.get("explanation", ""))
    while True:
        ans = input("Continue? [y/N]: ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("", "n", "no"):
            return False


def exec_calls(candidate, page: Page) -> List[Tuple[str, Dict[str, Any]]]:
    """Execute all function_call items from model response.
    Returns: list of (function_name, result_payload)
    """
    results: List[Tuple[str, Dict[str, Any]]] = []
    function_calls = [
        p.function_call for p in candidate.content.parts if getattr(p, "function_call", None)
    ]

    for fc in function_calls:
        name = fc.name
        args = dict(fc.args or {})
        extra: Dict[str, Any] = {}

        # HITL — confirm potentially risky step
        if "safety_decision" in args:
            if not ask_confirmation(args["safety_decision"]):
                print("⛔ User denied. Stopping.")
                results.append((name, {"error": "user_denied"}))
                return results
            extra["safety_acknowledgement"] = True

        print(f"→ {name} {args}")
        try:
            if name == "open_web_browser":
                pass  # browser already open
            elif name == "wait_5_seconds":
                time.sleep(5)
            elif name == "go_back":
                page.go_back()
            elif name == "go_forward":
                page.go_forward()
            elif name == "search":
                # Simple example: just navigate to Google
                page.goto("https://www.google.com")
            elif name == "navigate":
                page.goto(args["url"])
            elif name == "click_at":
                page.mouse.click(denorm_x(args["x"]), denorm_y(args["y"]))
            elif name == "hover_at":
                page.mouse.move(denorm_x(args["x"]), denorm_y(args["y"]))
            elif name == "type_text_at":
                x, y = denorm_x(args["x"]), denorm_y(args["y"])
                page.mouse.click(x, y)
                if args.get("clear_before_typing", True):
                    page.keyboard.press("Meta+A")
                    page.keyboard.press("Backspace")
                page.keyboard.type(args["text"])
                if args.get("press_enter", True):
                    page.keyboard.press("Enter")
            elif name == "key_combination":
                page.keyboard.press(args["keys"])  # e.g., "Control+A" or "Enter"
            elif name == "scroll_document":
                direction = str(args.get("direction", "down")).lower()
                if direction == "down":
                    page.keyboard.press("PageDown")
                elif direction == "up":
                    page.keyboard.press("PageUp")
                elif direction == "left":
                    page.evaluate("window.scrollBy(-400, 0)")
                elif direction == "right":
                    page.evaluate("window.scrollBy(400, 0)")
            elif name == "scroll_at":
                page.mouse.move(denorm_x(args["x"]), denorm_y(args["y"]))
                magnitude = int(args.get("magnitude", 800))
                direction = str(args.get("direction", "down")).lower()
                dy = magnitude if direction == "down" else -magnitude
                page.mouse.wheel(0, dy)
            elif name == "drag_and_drop":
                sx, sy = denorm_x(args["x"]), denorm_y(args["y"])  # source
                dx, dy = denorm_x(args["destination_x"]), denorm_y(args["destination_y"])  # dest
                page.mouse.move(sx, sy)
                page.mouse.down()
                page.mouse.move(dx, dy, steps=10)
                page.mouse.up()
            else:
                print(f"⚠ Not implemented: {name}")
                extra["warning"] = "unimplemented_action"

            try:
                page.wait_for_load_state(timeout=5000)
            except Exception:
                pass
            time.sleep(0.6)

            results.append((name, extra))
        except Exception as e:
            print(f"❌ Error in {name}: {e}")
            results.append((name, {"error": str(e), **extra}))

    return results


def build_function_responses(page: Page, results: List[Tuple[str, Dict[str, Any]]]) -> List[types.FunctionResponse]:
    screenshot = page.screenshot(type="png")
    url = page.url
    responses: List[types.FunctionResponse] = []
    for name, payload in results:
        data = {"url": url, **payload}
        responses.append(
            types.FunctionResponse(
                name=name,
                response=data,
                parts=[
                    types.FunctionResponsePart(
                        inline_data=types.FunctionResponseBlob(
                            mime_type="image/png", data=screenshot
                        )
                    )
                ],
            )
        )
    return responses


def load_api_key() -> str:
    key_path = Path(__file__).with_name("gemini_api_key")
    if not key_path.exists():
        raise RuntimeError("Missing API key file. Create 'gemini_api_key' next to agent.py with your key.")
    key = key_path.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError("'gemini_api_key' is empty. Put your API key on the first line.")
    return key


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python agent.py \"<your goal>\"")
        sys.exit(1)

    # Accept the whole remaining argv as goal (supports unquoted multi-word inputs)
    goal = " ".join(sys.argv[1:]).strip()
    api_key = load_api_key()
    client = genai.Client(api_key=api_key)
    print("🎯 Goal:", goal)

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT})
    page = context.new_page()

    try:
        # initial page + screenshot
        page.goto("https://www.google.com")
        initial_png = page.screenshot(type="png")

        # Computer Use tool config
        config = types.GenerateContentConfig(
            tools=[
                types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER,
                    )
                )
            ],
            thinking_config=types.ThinkingConfig(include_thoughts=True),
        )

        # initial content (goal + screenshot)
        contents: List[Content] = [
            Content(
                role="user",
                parts=[
                    Part(text=goal),
                    Part.from_bytes(data=initial_png, mime_type="image/png"),
                ],
            )
        ]

        # agent loop
        for turn in range(10):
            print(f"\n----- TURN {turn+1} -----")
            resp = client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=config,
            )
            cand = resp.candidates[0]
            contents.append(cand.content)

            # if no function_call — output text and exit
            if not any(getattr(p, "function_call", None) for p in cand.content.parts):
                final_text = " ".join(
                    [p.text for p in cand.content.parts if getattr(p, "text", None)]
                )
                print("\n✅ Done:", final_text)
                break

            # otherwise execute actions and return FunctionResponse with new screenshot
            print("▶ Executing actions…")
            results = exec_calls(cand, page)
            frs = build_function_responses(page, results)
            contents.append(Content(role="user", parts=[Part(function_response=fr) for fr in frs]))

        else:
            print("\n⏹ Reached step limit. Stopping.")

    finally:
        print("\nClosing browser…")
        browser.close()
        pw.stop()


if __name__ == "__main__":
    main()
