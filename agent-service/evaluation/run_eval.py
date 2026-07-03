"""
Evaluation runner for Meeting Prep & Follow-up Agent.

Usage:
    # Run against the live agent-service API (requires uvicorn running on :8000)
    python evaluation/run_eval.py

    # Run against a specific URL
    python evaluation/run_eval.py --url http://localhost:8000

What it does:
    1. Reads test_cases.json
    2. For each case, calls the appropriate agent endpoint
    3. Validates the response against expected criteria
    4. Reports a pass/fail score per test and overall

Scoring criteria per test:
  - Each expected field that passes = 1 point
  - Total possible = number of expected keys * number of tests
  - Score = passed / possible
"""

import argparse
import json
import sys
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"


def call_agent(url: str, mode: str, payload: dict) -> dict:
    endpoint = f"{url}/meetings/{mode}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_error_body": e.read().decode("utf-8")}
    except Exception as e:
        return {"_error": str(e)}


def evaluate(test: dict, response: dict) -> dict:
    results = {}
    expected = test["expected"]

    if "_http_error" in response or "_error" in response:
        return {"error": response.get("_error", response.get("_http_error")), "passed": 0, "total": len(expected)}

    # --- Prep checks ---
    if test["mode"] == "prep":
        if expected.get("has_attendees"):
            attendees = response.get("attendees", [])
            results["has_attendees"] = isinstance(attendees, list) and len(attendees) > 0
        if expected.get("has_background"):
            bg = response.get("background", "")
            results["has_background"] = isinstance(bg, str) and len(bg) > 20
        if expected.get("has_talking_points"):
            tps = response.get("talking_points", [])
            results["has_talking_points"] = isinstance(tps, list) and len(tps) >= expected.get("min_talking_points", 1)
        if expected.get("notes_missing_data"):
            bg = response.get("background", "")
            results["notes_missing_data"] = any(w in bg.lower() for w in ["no", "not found", "empty", "unavailable", "could not"])

    # --- Followup checks ---
    elif test["mode"] == "followup":
        if expected.get("has_summary"):
            summary = response.get("summary", "")
            results["has_summary"] = isinstance(summary, str) and len(summary) > 20
        if expected.get("has_action_items") is True:
            items = response.get("action_items", [])
            results["has_action_items"] = isinstance(items, list) and len(items) >= expected.get("min_action_items", 1)
        elif expected.get("has_action_items") is False:
            items = response.get("action_items", [])
            results["no_action_items"] = isinstance(items, list) and len(items) == 0
        if expected.get("owners_identified"):
            items = response.get("action_items", [])
            if isinstance(items, list) and len(items) > 0:
                results["owners_identified"] = all(
                    isinstance(i.get("owner"), str) and len(i["owner"].strip()) > 0 for i in items
                )
            else:
                results["owners_identified"] = False
        if expected.get("deadlines_identified"):
            items = response.get("action_items", [])
            if isinstance(items, list) and len(items) > 0:
                results["deadlines_identified"] = all(
                    isinstance(i.get("deadline"), str) and len(i["deadline"].strip()) > 0 for i in items
                )
            else:
                results["deadlines_identified"] = False
        if expected.get("graceful_handling"):
            results["graceful_handling"] = "_error" not in response and "_http_error" not in response

    passed = sum(1 for v in results.values() if v is True)
    return {"checks": results, "passed": passed, "total": len(expected)}


def main():
    parser = argparse.ArgumentParser(description="Evaluate agent output against test cases")
    parser.add_argument("--url", default=BASE_URL, help="Agent service URL")
    parser.add_argument("--cases", default="evaluation/test_cases.json", help="Path to test cases JSON")
    args = parser.parse_args()

    with open(args.cases, "r") as f:
        test_cases = json.load(f)

    print(f"Running {len(test_cases)} evaluation test(s) against {args.url}\n")

    total_passed = 0
    total_possible = 0
    failures = []

    for tc in test_cases:
        tid = tc["id"]
        print(f"  [{tid}] {tc['description']}")

        if tc["mode"] == "prep":
            resp = call_agent(args.url, "prep", {"user_id": "eval-user", "meeting_id": tc["meeting_id"]})
        else:
            resp = call_agent(args.url, "followup", {"user_id": "eval-user", "transcript": tc["transcript"]})

        result = evaluate(tc, resp)
        total_passed += result["passed"]
        total_possible += result["total"]

        status = "PASS" if result["passed"] == result["total"] else "FAIL"
        if "error" in result:
            print(f"    ERROR: {result['error']}")
        else:
            detail = ", ".join(f"{k}={v}" for k, v in result["checks"].items())
            print(f"    {status} ({result['passed']}/{result['total']}) [{detail}]")

        if status == "FAIL":
            failures.append(tid)

        print()

    score = (total_passed / total_possible * 100) if total_possible > 0 else 0
    print(f"{'='*50}")
    print(f"Score: {total_passed}/{total_possible} ({score:.1f}%)")
    if failures:
        print(f"Failed tests: {', '.join(failures)}")
    print(f"{'='*50}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
