"""Lossless extraction of explicit bilingual entries, never a dictionary lookup."""
from __future__ import annotations

import re

_ENTRY = re.compile(r"^\s*(?:(?:[-*]|\d+[.)、])\s*)?(?P<word>[A-Za-z]+(?:[ '-][A-Za-z]+){0,4})\s*(?:[：:]|[—–]\s*|\s+(?=[a-z]+\.|[\u4e00-\u9fff]))\s*(?P<meaning>.+?)\s*$")
_POS = re.compile(r'^(?:(?:n|v|vt|vi|adj|adv|prep|conj|pron|det|interj|aux|num)\.|名词|动词|形容词|副词)\s*', re.I)


def explicit_entries(text, title=''):
    """Only source-provided meanings; prose, code, URLs and unknown words stay with the model."""
    learning = bool(re.search(r'英语|英文|单词|词汇|英译|vocabulary|word\s+list', title + '\n' + text, re.I))
    cards, seen, fenced = [], set(), False
    for line in text.splitlines():
        if line.lstrip().startswith(('```', '~~~')):
            fenced = not fenced
            continue
        if fenced or len(line) > 180 or re.search(r'https?://', line):
            continue
        match = _ENTRY.fullmatch(line)
        if not match:
            continue
        word, meaning = match['word'].strip(), match['meaning'].strip()
        if word.casefold() in {'todo', 'fixme', 'note', 'warning', 'error'} and not _POS.match(meaning):
            continue
        if not re.search(r'[\u4e00-\u9fff]', meaning) or (not learning and not _POS.match(meaning)):
            continue
        if re.search(r'[{}<>]|https?://', meaning) or len(word) > 40 or len(f'{word}：{meaning}') > 180 or (word, meaning) in seen:
            continue
        seen.add((word, meaning))
        cards.append({'domain': 'language', 'topic': '英语词汇', 'kind': 'knowledge', 'format': 'concept',
                      'title': word, 'summary': f'{word}：{meaning}', 'points': [], 'quote': line,
                      'terms': [word]})
    return cards


def contextual_entry(question, reply):
    """Resolve a single explicit vocabulary question against its own short definition."""
    match = re.fullmatch(r"\s*(?:请问|问一下|单词)?\s*['\"“‘]?([A-Za-z]+(?:[ '-][A-Za-z]+){0,3})['\"”’]?\s*(?:是什么意思|什么意思|的意思是什么|怎么翻译)[？?。！!\s]*", question)
    answer = reply.strip()
    if not match or len(answer) > 130 or not re.match(r'^(?:它|这个词|该词)\s*(?:是[^。！？\n]{0,20}[，,]\s*)?(?:的)?(?:意思是|表示|意为|可译为)', answer):
        return []
    word = match[1]
    if len(word) > 40 or not re.search(r'[\u4e00-\u9fff]', answer):
        return []
    return [{'domain': 'language', 'topic': '英语词汇', 'kind': 'knowledge', 'format': 'concept',
             'title': word, 'summary': f'{word}：{answer}', 'points': [], 'quote': answer, 'terms': [word]}]
