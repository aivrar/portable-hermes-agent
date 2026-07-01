#!/usr/bin/env python3
"""Comprehensive test suite for all 45 Hermes custom tools."""
import sys, os, json, importlib.util, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load env
from dotenv import load_dotenv
load_dotenv(".env", encoding="utf-8")

sys.modules["tools"] = type(sys)("tools")
sys.modules["tools"].__path__ = ["tools"]

spec_reg = importlib.util.spec_from_file_location("tools.registry", "tools/registry.py")
mod_reg = importlib.util.module_from_spec(spec_reg)
sys.modules["tools.registry"] = mod_reg
spec_reg.loader.exec_module(mod_reg)
registry = mod_reg.registry

modules = [
    ("tools.lm_studio_tools", "tools/lm_studio_tools.py"),
    ("tools.extension_tools", "tools/extension_tools.py"),
    ("tools.gpu_tool", "tools/gpu_tool.py"),
    ("tools.model_switcher_tool", "tools/model_switcher_tool.py"),
    ("tools.run_python_tool", "tools/run_python_tool.py"),
    ("tools.update_hermes_tool", "tools/update_hermes_tool.py"),
    ("tools.tool_maker", "tools/tool_maker.py"),
    ("tools.workflow_tool", "tools/workflow_tool.py"),
]
for modname, path in modules:
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)

passed = 0
failed = 0
skipped = 0
fail_list = []

def test(name, result_json, check_fn=None, expect_error=False):
    global passed, failed, skipped
    try:
        r = json.loads(result_json)
        err = str(r.get("error", ""))
        down_keywords = ["unreachable", "connection", "refused", "not running", "timed out", "discover", "offline"]
        is_down = any(x in err.lower() for x in down_keywords)
        if is_down and not expect_error:
            print(f"  SKIP  {name} (service offline)")
            skipped += 1
            return r
        if expect_error:
            if "error" in r:
                print(f"  PASS  {name} (expected error)")
                passed += 1
                return r
        if check_fn and not check_fn(r):
            print(f"  FAIL  {name}: {json.dumps(r)[:200]}")
            failed += 1
            fail_list.append(name)
            return r
        if not check_fn and "error" in r:
            print(f"  FAIL  {name}: {err[:200]}")
            failed += 1
            fail_list.append(name)
            return r
        print(f"  PASS  {name}")
        passed += 1
        return r
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        failed += 1
        fail_list.append(name)
        return {}

print("=" * 60)
print("HERMES TOOL TEST SUITE - ALL 45 TOOLS")
print("=" * 60)

# ==================== GPU (1) ====================
print("\n--- GPU ---")
test("gpu_info", registry.dispatch("gpu_info", {}),
     lambda r: len(r.get("gpus", [])) > 0)

# ==================== RUN PYTHON (1) ====================
print("\n--- Run Python ---")
test("run_python", registry.dispatch("run_python", {"code": "print(2+2)"}),
     lambda r: "4" in r.get("stdout", ""))

# ==================== MODEL SWITCHER (1) ====================
print("\n--- Model Switcher ---")
cur_model = os.environ.get("LLM_MODEL", "google/gemini-2.5-flash")
test("switch_model", registry.dispatch("switch_model", {"model": "test-xyz", "provider": "openrouter"}),
     lambda r: r.get("switched") == True)
registry.dispatch("switch_model", {"model": cur_model, "provider": "openrouter"})

# ==================== LM STUDIO (10) ====================
print("\n--- LM Studio ---")
test("lm_studio_status", registry.dispatch("lm_studio_status", {}))
test("lm_studio_models", registry.dispatch("lm_studio_models", {}))
test("lm_studio_models (search)", registry.dispatch("lm_studio_models", {"search": "qwen"}))
test("lm_studio_search", registry.dispatch("lm_studio_search", {"query": "phi-4", "limit": 2}))
test("lm_studio_model_info (none)", registry.dispatch("lm_studio_model_info", {}), expect_error=True)

# Try load
load_result = registry.dispatch("lm_studio_load", {
    "model_path": "Qwen/Qwen2.5-1.5B-Instruct-GGUF/qwen2.5-1.5b-instruct-q8_0.gguf",
    "gpu_index": 0, "context_length": 4096,
})
load_r = json.loads(load_result)
if load_r.get("loaded"):
    ident = load_r["identifier"]
    print(f"  PASS  lm_studio_load (id={ident})")
    passed += 1

    test("lm_studio_model_info", registry.dispatch("lm_studio_model_info", {"model_id": ident}),
         lambda r: r.get("context_length") is not None)
    test("lm_studio_tokenize", registry.dispatch("lm_studio_tokenize", {"text": "Hello world", "model_id": ident}),
         lambda r: r.get("token_count", 0) > 0)
    test("lm_studio_chat", registry.dispatch("lm_studio_chat", {"prompt": "Say OK", "max_tokens": 10}),
         lambda r: len(r.get("response", "")) > 0)
    test("lm_studio_embed", registry.dispatch("lm_studio_embed", {"text": "test embedding"}))
    test("lm_studio_unload", registry.dispatch("lm_studio_unload", {"model_id": ident}),
         lambda r: r.get("unloaded") == True)
else:
    err = load_r.get("error", "")
    if any(x in err.lower() for x in ["discover", "connection", "refused"]):
        print("  SKIP  lm_studio_load (LM Studio offline)")
        skipped += 1
        for n in ["lm_studio_model_info", "lm_studio_tokenize", "lm_studio_chat", "lm_studio_embed", "lm_studio_unload"]:
            print(f"  SKIP  {n} (LM Studio offline)")
            skipped += 1
    else:
        print(f"  FAIL  lm_studio_load: {err}")
        failed += 1
        fail_list.append("lm_studio_load")
        skipped += 5

print("  SKIP  lm_studio_download (destructive)")
skipped += 1

# ==================== MUSIC (7) ====================
print("\n--- Music Server ---")
for name, args in [
    ("music_status", {}),
    ("music_models", {}),
    ("music_model_load", {"model": "musicgen"}),
    ("music_model_unload", {"model": "musicgen"}),
    ("music_generate", {"prompt": "test", "duration": 5}),
    ("music_outputs", {}),
    ("music_install", {"model": "musicgen"}),
]:
    test(name, registry.dispatch(name, args))

# ==================== TTS (7) ====================
print("\n--- TTS Server ---")
for name, args in [
    ("tts_server_status", {}),
    ("tts_server_models", {}),
    ("tts_server_model_load", {"model": "kokoro"}),
    ("tts_server_model_unload", {"model": "kokoro"}),
    ("tts_server_generate", {"text": "test"}),
    ("tts_server_voices", {"model": "kokoro"}),
    ("tts_server_jobs", {}),
]:
    test(name, registry.dispatch(name, args))

# ==================== COMFYUI (7) ====================
print("\n--- ComfyUI ---")
for name, args in [
    ("comfyui_status", {}),
    ("comfyui_instances", {}),
    ("comfyui_instance_start", {"instance_id": "test"}),
    ("comfyui_instance_stop", {"instance_id": "test"}),
    ("comfyui_generate", {"prompt": "test"}),
    ("comfyui_models", {}),
    ("comfyui_nodes", {}),
]:
    test(name, registry.dispatch(name, args))

# ==================== TOOL MAKER (3) ====================
print("\n--- Tool Maker ---")
test("create_tool (api)", registry.dispatch("create_tool", {
    "name": "test_api_tool", "description": "Test API", "mode": "api",
    "url": "https://httpbin.org/get", "method": "GET",
    "query_params": [{"name": "q", "type": "string", "description": "test"}],
}), lambda r: r.get("created") == True)

test("create_tool (code)", registry.dispatch("create_tool", {
    "name": "test_math", "description": "Add numbers", "mode": "code",
    "code": "a = int(args.get('a', 0))\nb = int(args.get('b', 0))\nreturn json.dumps({'result': a + b})",
    "parameters": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]},
}), lambda r: r.get("created") == True)

# Test dispatching the created tool
test("dispatch custom tool", registry.dispatch("test_math", {"a": 10, "b": 32}),
     lambda r: r.get("result") == 42)

test("list_custom_tools", registry.dispatch("list_custom_tools", {}),
     lambda r: r.get("count", 0) >= 2)

# Cleanup
registry.dispatch("delete_tool", {"name": "test_api_tool"})
registry.dispatch("delete_tool", {"name": "test_math"})
test("delete_tool", registry.dispatch("delete_tool", {"name": "nonexistent"}), expect_error=True)

# ==================== WORKFLOWS (6) ====================
print("\n--- Workflows ---")
test("workflow_create", registry.dispatch("workflow_create", {
    "name": "test-wf",
    "description": "Test workflow",
    "steps": [
        {"id": "gpu", "tool": "gpu_info", "args": {}},
        {"id": "py", "tool": "run_python", "args": {"code": "print('wf-ok')"}},
    ],
}), lambda r: r.get("created") == True)

test("workflow_list", registry.dispatch("workflow_list", {}),
     lambda r: r.get("count", 0) >= 1)

test("workflow_show", registry.dispatch("workflow_show", {"name": "test-wf"}),
     lambda r: r.get("name") == "test-wf")

wf_run = test("workflow_run", registry.dispatch("workflow_run", {"name": "test-wf"}),
     lambda r: r.get("status") == "completed")

# Test inline workflow with variables
test("workflow_run (inline)", registry.dispatch("workflow_run", {
    "steps": [
        {"id": "calc", "tool": "run_python", "args": {"code": "print(7*6)"}},
    ],
}), lambda r: r.get("status") == "completed")

test("workflow_schedule", registry.dispatch("workflow_schedule", {"name": "test-wf", "cron": "0 8 * * *"}),
     lambda r: r.get("scheduled") == True)

test("workflow_delete", registry.dispatch("workflow_delete", {"name": "test-wf"}),
     lambda r: r.get("deleted") == True)

# ==================== HERMES UPDATE (2) ====================
print("\n--- Hermes Update ---")
test("check_hermes_updates", registry.dispatch("check_hermes_updates", {}),
     lambda r: "commits_behind" in r)
print("  SKIP  update_hermes (destructive)")
skipped += 1

# ==================== SUMMARY ====================
print("\n" + "=" * 60)
print(f"RESULTS: {passed} PASSED | {failed} FAILED | {skipped} SKIPPED")
print(f"TOTAL:   {passed + failed + skipped} / 45 tools")
print("=" * 60)
if fail_list:
    print("\nFAILURES:")
    for name in fail_list:
        print(f"  X {name}")
else:
    print("\nAll testable tools passed!")
