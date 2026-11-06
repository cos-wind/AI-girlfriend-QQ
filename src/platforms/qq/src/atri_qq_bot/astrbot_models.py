"""Translate saved desktop profiles to native AstrBot providers, without I/O.

Only an explicit, offline deployment may persist this private configuration.
The resulting dictionary contains credentials and must never be sent to the UI.
"""
from copy import deepcopy
from hashlib import sha256


def provider_id(profile_id: str) -> str:
    return 'atri-model-' + sha256(profile_id.encode('utf-8')).hexdigest()[:16]


def merge_model_profiles(config: dict, profiles: list[dict]) -> tuple[dict, dict[str, str]]:
    """Upsert usable chat/vision profiles, preserving unrelated providers/settings.

    Embeddings are not chat providers. Missing credentials are skipped rather
    than borrowed from another profile. Deletions never remove existing entries.
    """
    result = deepcopy(config)
    providers = result.setdefault('provider', [])
    sources = result.setdefault('provider_sources', [])
    mapping = {}
    seen = set()
    for profile in profiles:
        if profile.get('model_type') not in {'chat', 'vision'}:
            continue
        identity = str(profile.get('id') or '').strip()
        base = str(profile.get('base_url') or '').strip().rstrip('/')
        model = str(profile.get('model') or '').strip()
        key = str(profile.get('api_key') or '').strip()
        if not all((identity, model, key)) or not base.startswith(('http://', 'https://')):
            continue
        if identity in seen:
            raise ValueError('模型档案ID重复，未同步')
        seen.add(identity)
        pid = provider_id(identity)
        sid = pid + '_source'
        source = dict(id=sid, type='openai_chat_completion', provider_type='chat_completion',
                      key=[key], api_base=base, timeout=90, proxy='', custom_headers={})
        provider = dict(id=pid, enable=True, model=model, provider_source_id=sid,
                        modalities=['image'] if profile['model_type'] == 'vision' else [],
                        custom_extra_body={})
        for entries, row in ((sources, source), (providers, provider)):
            existing = next((item for item in entries if item.get('id') == row['id']), None)
            if existing is None:
                entries.append(row)
            else:
                existing.update(row)
        mapping[identity] = pid
    return result, mapping
