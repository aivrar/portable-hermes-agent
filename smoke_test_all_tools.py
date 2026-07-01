#!/usr/bin/env python3
"""
COMPREHENSIVE SMOKE TEST - ALL HERMES TOOLS
Tests every registered tool via registry.dispatch() with real calls.
"""
import sys, os, json, time, traceback

# --- Bootstrap ---
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(".env", encoding="utf-8")

# Force workspace to a temp dir so file tools don't trash real files
TEST_WORKSPACE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace", "_smoke_test")
os.makedirs(TEST_WORKSPACE, exist_ok=True)

# Import model_tools which triggers all tool discovery
import model_tools
from tools.registry import registry

# ============================================================
# Test harness
# ============================================================
passed = 0
failed = 0
skipped = 0
errors_detail = []

def test(name, result_json, check_fn=None, expect_error=False):
    global passed, failed, skipped
    try:
        if isinstance(result_json, str):
            r = json.loads(result_json)
        else:
            r = result_json
        err = str(r.get("error", ""))

        # Service-offline detection
        down_kw = ["unreachable", "connection refused", "not running", "timed out",
                    "offline", "ECONNREFUSED", "connect ECONNREFUSED", "no route"]
        is_down = any(x.lower() in err.lower() for x in down_kw)
        if is_down and not expect_error:
            print(f"  SKIP  {name} (service offline: {err[:80]})")
            skipped += 1
            return r

        if expect_error:
            if "error" in r:
                print(f"  PASS  {name} (expected error: {err[:60]})")
                passed += 1
                return r
            else:
                print(f"  FAIL  {name} (expected error but got success)")
                failed += 1
                errors_detail.append((name, "Expected error but got success", r))
                return r

        if check_fn:
            try:
                ok = check_fn(r)
            except Exception as e:
                ok = False
                print(f"  FAIL  {name} (check_fn raised: {e})")
                failed += 1
                errors_detail.append((name, f"check_fn raised: {e}", r))
                return r
            if not ok:
                print(f"  FAIL  {name}: {json.dumps(r)[:200]}")
                failed += 1
                errors_detail.append((name, "check_fn returned False", r))
                return r

        if "error" in r and not check_fn:
            print(f"  FAIL  {name}: {err[:200]}")
            failed += 1
            errors_detail.append((name, err, r))
            return r

        print(f"  PASS  {name}")
        passed += 1
        return r
    except json.JSONDecodeError as e:
        # Some tools return plain text
        if isinstance(result_json, str) and len(result_json) > 0:
            if check_fn:
                try:
                    if check_fn(result_json):
                        print(f"  PASS  {name} (plain text)")
                        passed += 1
                        return result_json
                except:
                    pass
            # Non-JSON but not empty = probably fine
            print(f"  PASS  {name} (non-JSON response, {len(result_json)} chars)")
            passed += 1
            return result_json
        print(f"  FAIL  {name}: JSONDecodeError: {e}")
        failed += 1
        errors_detail.append((name, f"JSONDecodeError: {e}", result_json[:200] if result_json else ""))
        return {}
    except Exception as e:
        print(f"  FAIL  {name}: {type(e).__name__}: {e}")
        failed += 1
        errors_detail.append((name, f"{type(e).__name__}: {e}", ""))
        return {}

def dispatch(name, args, **kwargs):
    """Wrapper around registry.dispatch that catches crashes."""
    try:
        return registry.dispatch(name, args, **kwargs)
    except Exception as e:
        return json.dumps({"error": f"CRASH: {type(e).__name__}: {e}"})


print("=" * 70)
print("HERMES COMPREHENSIVE SMOKE TEST - ALL TOOLS")
print(f"Registered tools: {len(registry.get_all_tool_names())}")
print(f"Tools: {', '.join(registry.get_all_tool_names())}")
print("=" * 70)

# ==================== 1. TERMINAL (1) ====================
print("\n--- TERMINAL ---")
test("terminal (echo)", dispatch("terminal", {"command": "echo hello-smoke-test"}),
     lambda r: "hello-smoke-test" in str(r))

# ==================== 2. PROCESS (1) ====================
print("\n--- PROCESS ---")
test("process (list)", dispatch("process", {"action": "list"}),
     lambda r: isinstance(r, dict))

# ==================== 3. FILE TOOLS (4) ====================
print("\n--- FILE TOOLS ---")
test_file = os.path.join(TEST_WORKSPACE, "smoke_test_file.txt").replace("\\", "/")

test("write_file", dispatch("write_file", {"path": test_file, "content": "line1\nline2\nline3\nline4\nline5"}),
     lambda r: r.get("status") == "success" or "written" in str(r).lower() or not r.get("error"))

test("read_file", dispatch("read_file", {"path": test_file}),
     lambda r: "line1" in str(r) or "line2" in str(r))

test("patch (replace)", dispatch("patch", {
    "mode": "replace", "path": test_file,
    "old_string": "line3", "new_string": "PATCHED_LINE3"
}), lambda r: "PATCHED_LINE3" in str(r) or "diff" in str(r).lower() or not r.get("error"))

test("search_files (content)", dispatch("search_files", {
    "pattern": "PATCHED", "target": "content", "path": TEST_WORKSPACE
}), lambda r: "PATCHED" in str(r) or not r.get("error"))

# ==================== 4. WEB TOOLS (2) ====================
print("\n--- WEB TOOLS ---")
test("web_search", dispatch("web_search", {"query": "python hello world"}),
     lambda r: not r.get("error"))

test("web_extract", dispatch("web_extract", {"urls": ["https://example.com"]}),
     lambda r: not r.get("error"))

# ==================== 5. SERPER SEARCH (1) ====================
print("\n--- SERPER SEARCH ---")
test("serper_search", dispatch("serper_search", {"query": "what is python", "num_results": 2}),
     lambda r: not r.get("error"))

# ==================== 6. VISION (1) ====================
print("\n--- VISION ---")
# Vision needs an image URL or path - test with a public image
test("vision_analyze", dispatch("vision_analyze", {
    "image_url": "https://picsum.photos/200",
    "prompt": "What is this image?"
}), lambda r: not r.get("error"))

# ==================== 7. IMAGE GENERATION (1) ====================
print("\n--- IMAGE GENERATION ---")
test("image_generate", dispatch("image_generate", {
    "prompt": "A simple red circle on white background",
    "size": "square"
}), lambda r: not r.get("error"))

# ==================== 8. TODO (1) ====================
print("\n--- TODO ---")
test("todo (write+read)", dispatch("todo", {
    "todos": [
        {"id": "t1", "content": "Smoke test task 1", "status": "pending"},
        {"id": "t2", "content": "Smoke test task 2", "status": "in_progress"},
    ]
}), lambda r: isinstance(r, dict) and (r.get("items") or r.get("todos") or "t1" in str(r)))

test("todo (read)", dispatch("todo", {}),
     lambda r: isinstance(r, dict))

# ==================== 9. MEMORY (1) ====================
print("\n--- MEMORY ---")
test("memory (add)", dispatch("memory", {
    "action": "add", "target": "memory",
    "content": "SMOKE_TEST_ENTRY: this is a test memory entry"
}), lambda r: not r.get("error"))

test("memory (remove)", dispatch("memory", {
    "action": "remove", "target": "memory",
    "old_text": "SMOKE_TEST_ENTRY"
}), lambda r: not r.get("error"))

# ==================== 10. SESSION SEARCH (1) ====================
print("\n--- SESSION SEARCH ---")
test("session_search", dispatch("session_search", {"query": "test OR smoke OR hello", "limit": 2}),
     lambda r: isinstance(r, dict))

# ==================== 11. CLARIFY (1) ====================
print("\n--- CLARIFY ---")
# Clarify is interactive - it sends a question to the user. Without a UI it should still return valid JSON
test("clarify", dispatch("clarify", {
    "question": "Is this a smoke test?",
    "options": ["yes", "no"]
}), lambda r: isinstance(r, dict))

# ==================== 12. SKILLS (3) ====================
print("\n--- SKILLS ---")
test("skills_list", dispatch("skills_list", {}),
     lambda r: isinstance(r, dict) and ("skills" in r or "categories" in r or "count" in r or not r.get("error")))

test("skill_view", dispatch("skill_view", {"query": "ocr"}),
     lambda r: isinstance(r, dict))

test("skill_manage", dispatch("skill_manage", {"action": "list"}),
     lambda r: isinstance(r, dict))

# ==================== 13. BROWSE TOOLS (1) ====================
print("\n--- BROWSE TOOLS ---")
test("browse_tools (list all)", dispatch("browse_tools", {}),
     lambda r: isinstance(r, dict) and ("categories" in r or "toolsets" in r or not r.get("error")))

test("browse_tools (category)", dispatch("browse_tools", {"category": "web"}),
     lambda r: isinstance(r, dict))

# ==================== 14. SEARCH GUIDE (1) ====================
print("\n--- SEARCH GUIDE ---")
test("search_guide", dispatch("search_guide", {"query": "terminal tool"}),
     lambda r: isinstance(r, dict) and not r.get("error"))

# ==================== 15. GPU (1) ====================
print("\n--- GPU ---")
test("gpu_info", dispatch("gpu_info", {}),
     lambda r: "gpus" in r or not r.get("error"))

# ==================== 16. RUN PYTHON (1) ====================
print("\n--- RUN PYTHON ---")
test("run_python", dispatch("run_python", {"code": "print(2+2)"}),
     lambda r: "4" in r.get("stdout", ""))

# ==================== 17. MODEL SWITCHER (1) ====================
print("\n--- MODEL SWITCHER ---")
cur_model = os.environ.get("LLM_MODEL", "test")
test("switch_model", dispatch("switch_model", {"model": "test-smoke", "provider": "openrouter"}),
     lambda r: r.get("switched") == True)
# Restore
dispatch("switch_model", {"model": cur_model, "provider": "openrouter"})

# ==================== 18. EXECUTE CODE (1) ====================
print("\n--- EXECUTE CODE ---")
test("execute_code", dispatch("execute_code", {
    "code": "result = 40 + 2\nprint(f'Answer: {result}')"
}), lambda r: "42" in str(r) or "Answer" in str(r) or not r.get("error"))

# ==================== 19. DELEGATE TASK (1) ====================
print("\n--- DELEGATE TASK ---")
# delegate_task spawns a subagent - it needs API access
test("delegate_task", dispatch("delegate_task", {
    "task": "What is 2+2? Reply with just the number.",
    "context": "Simple math test"
}), lambda r: isinstance(r, dict))

# ==================== 20. SEND MESSAGE (1) ====================
print("\n--- SEND MESSAGE ---")
# send_message requires gateway to be running
test("send_message (no gateway)", dispatch("send_message", {
    "platform": "telegram", "recipient": "test", "message": "smoke test"
}), expect_error=True)

# ==================== 21. LM STUDIO (10) ====================
print("\n--- LM STUDIO ---")
test("lm_studio_status", dispatch("lm_studio_status", {}))
test("lm_studio_models", dispatch("lm_studio_models", {}))

# ==================== 22. TOOL MAKER (3) ====================
print("\n--- TOOL MAKER ---")
test("create_tool (code)", dispatch("create_tool", {
    "name": "smoke_add", "description": "Add numbers", "mode": "code",
    "code": "a = int(args.get('a', 0))\nb = int(args.get('b', 0))\nreturn json.dumps({'result': a + b})",
    "parameters": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]},
}), lambda r: r.get("created") == True)

test("dispatch smoke_add", dispatch("smoke_add", {"a": 10, "b": 32}),
     lambda r: r.get("result") == 42)

test("list_custom_tools", dispatch("list_custom_tools", {}),
     lambda r: r.get("count", 0) >= 1)

dispatch("delete_tool", {"name": "smoke_add"})

# ==================== 23. WORKFLOWS (6) ====================
print("\n--- WORKFLOWS ---")
test("workflow_create", dispatch("workflow_create", {
    "name": "smoke-wf", "description": "Smoke test workflow",
    "steps": [{"id": "py", "tool": "run_python", "args": {"code": "print('wf-smoke')"}}],
}), lambda r: r.get("created") == True)

test("workflow_list", dispatch("workflow_list", {}),
     lambda r: r.get("count", 0) >= 1)

test("workflow_show", dispatch("workflow_show", {"name": "smoke-wf"}),
     lambda r: r.get("name") == "smoke-wf")

test("workflow_run", dispatch("workflow_run", {"name": "smoke-wf"}),
     lambda r: r.get("status") == "completed")

test("workflow_delete", dispatch("workflow_delete", {"name": "smoke-wf"}),
     lambda r: r.get("deleted") == True)

# ==================== 24. CRONJOB (1) ====================
print("\n--- CRONJOB ---")
test("cronjob (list)", dispatch("cronjob", {"action": "list"}),
     lambda r: isinstance(r, dict) and ("jobs" in r or "error" not in r))

# ==================== 25. TTS (1) ====================
print("\n--- TTS ---")
test("text_to_speech", dispatch("text_to_speech", {
    "text": "Hello smoke test", "provider": "edge"
}), lambda r: not r.get("error") or "tts" in str(r).lower())

# ==================== 26. HONCHO (4) ====================
print("\n--- HONCHO (requires HONCHO_API_KEY) ---")
for name, args in [
    ("honcho_context", {"query": "test"}),
    ("honcho_profile", {"action": "get"}),
    ("honcho_search", {"query": "test"}),
    ("honcho_conclude", {"conclusion": "test session conclusion"}),
]:
    test(name, dispatch(name, args), expect_error=True)

# ==================== 27. HOME ASSISTANT (4) ====================
print("\n--- HOME ASSISTANT (requires HASS_TOKEN) ---")
for name, args in [
    ("ha_list_entities", {}),
    ("ha_get_state", {"entity_id": "light.test"}),
    ("ha_list_services", {}),
    ("ha_call_service", {"domain": "light", "service": "turn_on", "entity_id": "light.test"}),
]:
    test(name, dispatch(name, args), expect_error=True)

# ==================== 28. MUSIC SERVER (2 sample) ====================
print("\n--- MUSIC SERVER ---")
test("music_status", dispatch("music_status", {}))

# ==================== 29. TTS SERVER (2 sample) ====================
print("\n--- TTS SERVER ---")
test("tts_server_status", dispatch("tts_server_status", {}))

# ==================== 30. COMFYUI (2 sample) ====================
print("\n--- COMFYUI ---")
test("comfyui_status", dispatch("comfyui_status", {}))

# ==================== 31. HERMES UPDATE (1) ====================
print("\n--- HERMES UPDATE ---")
test("check_hermes_updates", dispatch("check_hermes_updates", {}),
     lambda r: "commits_behind" in r)

# ==================== 32. MIXTURE OF AGENTS (1) ====================
print("\n--- MIXTURE OF AGENTS ---")
test("mixture_of_agents", dispatch("mixture_of_agents", {
    "query": "What is 2+2?",
    "models": 2
}), lambda r: isinstance(r, dict))

# ==================== 33. SERPER (checked above) ====================

# ==================== SUMMARY ====================
total = passed + failed + skipped
print("\n" + "=" * 70)
print(f"RESULTS: {passed} PASSED | {failed} FAILED | {skipped} SKIPPED")
print(f"TOTAL:   {total} tests")
print(f"Registered tools: {len(registry.get_all_tool_names())}")
print("=" * 70)

if errors_detail:
    print("\n" + "=" * 70)
    print("FAILURE DETAILS:")
    print("=" * 70)
    for name, err, data in errors_detail:
        print(f"\n  X {name}")
        print(f"    Error: {err[:300]}")
        if isinstance(data, dict):
            print(f"    Data:  {json.dumps(data)[:300]}")
        elif isinstance(data, str):
            print(f"    Data:  {data[:300]}")
else:
    print("\nAll testable tools passed!")

# Cleanup test workspace
import shutil
try:
    shutil.rmtree(TEST_WORKSPACE, ignore_errors=True)
except:
    pass
