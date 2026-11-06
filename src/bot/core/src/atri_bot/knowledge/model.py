"""Model transport for derived knowledge, sharing the existing inference queue."""
from contextlib import ExitStack
from dataclasses import replace

import httpx

from atri_bot.llm_tools import ollama_completion
from atri_shared.runtime.inference_lock import InferencePriority, inference_resource_lease_sync


def complete(config, payload, *, task):
    local = ollama_completion.is_local_endpoint(config.openai_base_url)
    with ExitStack() as stack:
        if local:
            stack.enter_context(inference_resource_lease_sync(
                f'knowledge-{task}:{config.openai_model}', timeout_seconds=35,
                priority=InferencePriority.BACKGROUND))
        client = stack.enter_context(httpx.Client(timeout=60, trust_env=not local))
        profile = (ollama_completion.load_profile(client, config.openai_base_url, config.openai_model)
                   if local else None)
        if local:
            # Knowledge JSON retains its original structured-output allowance.
            # The shorter interactive-chat cap would cut multi-card responses.
            profile = replace(profile or ollama_completion.ModelProfile(),
                              output_limit=int(payload['max_tokens']))
        url, body, native = ollama_completion.prepare(config.openai_base_url, payload, profile=profile)
        response = client.post(url, headers={'Authorization': f'Bearer {config.openai_api_key}'}, json=body)
        response.raise_for_status()
        data = ollama_completion.completion(response.json()) if native else response.json()
        if data['choices'][0].get('finish_reason') == 'length':
            raise ValueError('知识整理输出被截断，请重试')
        return data['choices'][0]['message']['content']
