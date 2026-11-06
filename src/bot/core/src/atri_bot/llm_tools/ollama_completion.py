"""Shared Ollama wire adapter; keep the existing OpenAI tool/reply contracts.

Ollama's /v1 API ignores options.num_ctx. Use its native endpoint only for the
known local service, with an explicit per-request context. No model creation,
global configuration, service restart, or new tool executor is involved.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import logging
import threading
import time
from urllib.parse import urlsplit

import httpx

LOG = logging.getLogger(__name__)
# llama.cpp's qwen2 pre-tokenizer, also used by Qwen3 GGUF models. Vocabulary
# and merges come from the *selected local model*, never from an account/name.
QWEN2_PATTERN = (r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}|"
                 r" ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+")
_profiles = {}
_profile_lock = threading.Lock()


@dataclass
class ModelProfile:
    tokenizer: object = None
    context_limit: int = 65536
    output_limit: int = 8192
    template_overhead: int = 1024

    def count(self, text):
        if self.tokenizer is None:
            return len(text.encode('utf-8'))
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)


def profile_from_metadata(data):
    info = data.get('model_info') or {}
    limits = [int(v) for k, v in info.items() if k.endswith('.context_length') and isinstance(v, int) and v > 0]
    profile = ModelProfile(context_limit=min([65536, *limits]))
    capabilities = data.get('capabilities')
    if isinstance(capabilities, list) and 'completion' in capabilities and 'thinking' not in capabilities:
        profile.output_limit = 2048
    if (info.get('tokenizer.ggml.model') == 'gpt2' and info.get('tokenizer.ggml.pre') == 'qwen2'
            and info.get('tokenizer.ggml.tokens') and info.get('tokenizer.ggml.merges')):
        from tokenizers import Tokenizer, Regex, models, pre_tokenizers
        vocab = {token: index for index, token in enumerate(info['tokenizer.ggml.tokens'])}
        merges = [tuple(merge.split(' ', 1)) for merge in info['tokenizer.ggml.merges']]
        tokenizer = Tokenizer(models.BPE(vocab, merges))
        tokenizer.pre_tokenizer = pre_tokenizers.Sequence([
            pre_tokenizers.Split(Regex(QWEN2_PATTERN), behavior='isolated'),
            pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)])
        profile.tokenizer = tokenizer
        # Count all message/tool JSON plus a generous template allowance. Never
        # divide byte counts by a guessed multilingual tokens-per-char ratio.
        profile.template_overhead += profile.count(str(data.get('template') or ''))
    return profile


def clear_profile_cache():
    with _profile_lock:
        _profiles.clear()


def load_profile(client, endpoint, model):
    if not is_local_endpoint(endpoint):
        return None
    key = (endpoint.rstrip('/'), model)
    with _profile_lock:
        cached = _profiles.get(key)
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
    url = urlsplit(endpoint)
    try:
        response = client.post(f'{url.scheme}://{url.netloc}/api/show',
            json={'model': model, 'verbose': True}, timeout=5.0)
        response.raise_for_status()
        profile = profile_from_metadata(response.json())
    except (httpx.HTTPError, ValueError, KeyError, TypeError, ImportError):
        # Unknown/custom providers retain the original byte upper bound; a
        # metadata failure must never silently revert to a truncated /v1 call.
        LOG.warning('desktop local tokenizer unavailable; using conservative context budget')
        return None
    with _profile_lock:
        if len(_profiles) >= 2:
            _profiles.pop(next(iter(_profiles)))
        _profiles[key] = (time.monotonic(), profile)
    return profile


async def load_profile_async(client, endpoint, model):
    """Async core counterpart, sharing tokenizer metadata/cache with desktop."""
    if not is_local_endpoint(endpoint):
        return None
    key = (endpoint.rstrip('/'), model)
    with _profile_lock:
        cached = _profiles.get(key)
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
    url = urlsplit(endpoint)
    try:
        response = await client.post(f'{url.scheme}://{url.netloc}/api/show',
            json={'model': model, 'verbose': True}, timeout=5.0)
        response.raise_for_status()
        profile = profile_from_metadata(response.json())
    except (httpx.HTTPError, ValueError, KeyError, TypeError, ImportError):
        LOG.warning('local tokenizer unavailable; using conservative context budget')
        return None
    with _profile_lock:
        if len(_profiles) >= 2:
            _profiles.pop(next(iter(_profiles)))
        _profiles[key] = (time.monotonic(), profile)
    return profile


def is_local_endpoint(endpoint):
    url = urlsplit(endpoint)
    return (url.scheme in {'http', 'https'} and url.hostname in {'localhost', '127.0.0.1', '::1'}
            and url.port == 11434 and url.path.rstrip('/') == '/v1')


class RequestContractError(ValueError):
    """Actionable local request limit, not malformed provider data."""


def prepare(endpoint, payload, *, profile=None):
    url = urlsplit(endpoint)
    if not is_local_endpoint(endpoint):
        return endpoint.rstrip("/") + "/chat/completions", payload, False
    choice = payload.get("tool_choice", "auto")
    # Native Ollama has no tool_choice contract. Preserve the established
    # OpenAI route for forced tools rather than relying on prompt compliance.
    if choice not in ("auto", "none"):
        return endpoint.rstrip("/") + "/chat/completions", payload, False
    messages = deepcopy(payload["messages"])
    names = {}
    for message in messages:
        for call in message.get("tool_calls", []):
            function = call["function"]
            names[call.get("id", "")] = function["name"]
            if isinstance(function.get("arguments"), str):
                function["arguments"] = json.loads(function["arguments"])
        if message.get("role") == "tool":
            message["tool_name"] = names.get(message.get("tool_call_id"), message.get("name", ""))
    tools = deepcopy(payload.get("tools", [])) if choice != "none" else []
    profile = profile or ModelProfile()
    output = min(max(1, int(payload.get('max_tokens', 8192))), profile.output_limit)
    budget = profile.count(json.dumps([messages, tools], ensure_ascii=False)) + output + profile.template_overhead + 32 * len(messages)
    context = max(8192, ((budget + 4095) // 4096) * 4096)
    context = min(context, profile.context_limit)
    if budget > context:
        raise RequestContractError("本地聊天上下文过长，请减少本轮材料或新开对话；未截断人格和历史")
    native = {"model": payload["model"], "messages": messages,
              "stream": bool(payload.get("stream", False)),
              "keep_alive": 0,
              "options": {"num_ctx": context, "num_predict": output,
                          "temperature": payload.get("temperature", .75)}}
    for key in ('frequency_penalty', 'presence_penalty', 'top_p', 'stop', 'seed'):
        if key in payload:
            native['options'][key] = deepcopy(payload[key])
    if tools:
        native["tools"] = tools
    return f"{url.scheme}://{url.netloc}/api/chat", native, True


def completion(data):
    if data.get("error"):
        return {"error": data["error"]}
    message = data.get("message") or {}
    public = {"role": "assistant", "content": message.get("content", "")}
    if message.get("tool_calls"):
        public["tool_calls"] = [_call(call, index) for index, call in enumerate(message["tool_calls"])]
    return {"choices": [{"message": public, "finish_reason": data.get("done_reason", "stop")}],
            "usage": {"prompt_tokens": data.get("prompt_eval_count", 0),
                      "completion_tokens": data.get("eval_count", 0)}}


def _call(call, index):
    function = call["function"]
    arguments = function.get("arguments", {})
    return {"id": call.get("id") or f"ollama-call-{index}", "type": "function",
            "function": {"name": function["name"], "arguments":
                         arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)}}


def stream_events(lines):
    """NDJSON -> existing desktop SSE event shape, never expose thinking."""
    next_index = 0
    for line in lines:
        if not line.strip():
            continue
        data = json.loads(line)
        if data.get("error"):
            yield {"error": data["error"]}
            return
        message = data.get("message") or {}
        delta = {"content": message.get("content", "")}
        calls = []
        for call in message.get("tool_calls", []):
            calls.append(dict(_call(call, next_index), index=next_index))
            next_index += 1
        if calls:
            delta["tool_calls"] = calls
        yield {"choices": [{"delta": delta, "finish_reason":
                            data.get("done_reason", "stop") if data.get("done") else None}]}
