"""Keep source evidence separate from a model's unsent claims.

Similarity is only a review trigger, never a fact/subject classifier. In
particular, speaker identity alone cannot establish the subject of a quotation.
"""
import re
from difflib import SequenceMatcher


def _interaction_claims(text, *, assistant=False):
    """Local dialogue actions, never assertions for persistent memory.

    A user may omit themselves only inside a stage direction, addressed to the
    bot. An assistant may narrate its own action at the start of a clause.
    Requests, quotes, hypotheticals and third-party subjects stay unresolved.
    """
    from atri_bot.memory.evidence import assertion_spans
    people = {'我': '亚托莉' if assistant else '当前用户',
              '你': '当前用户' if assistant else '亚托莉', '亚托莉': '亚托莉'}
    stages = [(m.start(), m.end()) for m in re.finditer(r'（[^（）\n]+）|\([^()\n]+\)', text)]
    for clause, start, end in assertion_spans(text):
        staged = any(left <= start and end <= right for left, right in stages)
        if staged:
            clause = clause.lstrip('（(').rstrip('）)').strip()
        match = re.match(
            r'^(?:(?:啊|哦|嗯|原来|不过|其实|现在|是|那|所以|而是|明明|确实)[～~！!\s]*){0,3}'
            r'(?P<actor>我|你|亚托莉)?(?P<also>也)?(?:正在|刚刚|已经|在|正|刚)?(?:轻轻)?'
            r'(?:给(?P<recipient>亚托莉|你|我)(?P<feed>投喂)|'
            r'(?P<verb>摸摸|摸|揉揉|揉|拍拍|拍|抱抱|抱|搂|安慰|哄|夸|亲亲|亲)'
            r'(?:了|着|过)?(?P<target>亚托莉|我|你)(?:的)?'
            r'(?P<body>脑袋|肩膀|头|脸|手|背)?(?=$|[呢呀啊哦啦了的着～~\s]))', clause)
        if not match:
            continue
        actor = match['actor']
        target = match['recipient'] or match['target']
        if actor is None:
            if not assistant and (not staged or target not in {'你', '亚托莉'}):
                continue
            actor = '我'
        if people[actor] == people[target]:
            continue
        verb = match['feed'] or match['verb']
        if len(verb) == 2 and verb[0] == verb[1]:
            verb = verb[0]
        body = {'脑袋': '头'}.get(match['body'], match['body'] or '')
        # 摸/揉/拍 require an explicit body part, so someone's pet/object
        # cannot be mistaken for that person receiving the action.
        if verb in {'摸', '揉', '拍'} and not body:
            continue
        yield (people[actor], verb, people[target], body), bool(match['also'])


def interaction_facts(text, *, assistant=False):
    """Resolve bounded two-person dialogue actions, not general semantic truth."""
    return {fact for fact, _ in _interaction_claims(text, assistant=assistant)}


def interaction_conflict(reply, user_text):
    expected = interaction_facts(user_text)
    for fact, reciprocal in _interaction_claims(reply, assistant=True):
        actor, verb, target, body = fact
        # “我也摸摸你的头” can be a new reciprocal action, not a restatement
        # of who performed the user's action.
        if reciprocal:
            continue
        if fact not in expected and (target, verb, actor, body) in expected:
            return True
    return False


def interaction_reply_issue(reply, user_text):
    """One shared acceptance gate for review triggers and final delivery."""
    if interaction_conflict(reply, user_text):
        return '互动施事与受事反转'
    if interaction_facts(user_text):
        def compact(value):
            value = re.sub(r'\[(?:表情|心情):[^\]\r\n]*\]', '', value)
            return re.sub(r'[\s，,。.!！?？～~（）()]', '', value)
        if compact(reply) == compact(user_text):
            return '原样复读用户动作，没有以亚托莉视角回应'
    return ''


def interaction_prompt(user_text):
    facts = interaction_facts(user_text)
    if not facts:
        return ''
    directions = '；'.join(f'{actor}对{target}：{verb}{body}'
                          for actor, verb, target, body in sorted(facts))
    return ('本轮用户陈述的互动方向：' + directions + '。这是用户表达的互动，不是工具确认的现实动作。'
            '以亚托莉为回复者，保持施事和受事；不要照搬用户原句的我/你，也不要在同一回复中前后颠倒。'
            '括号动作是当前用户的互动表达，不是让你复述的台词；按该方向表达自己的反应。'
            '当前动作已经明确，旧动作只作前情；不要再问用户这次做的是哪种动作。'
            '不要凭动作或自己以前的猜测断定用户在哭、难过或需要安慰。'
            '自然表达自己的反应即可，不输出这段校对说明。')


def _body(message):
    # A private message may contain a literal colon; it is not a speaker tag.
    # Keeping the full text is enough for the conservative overlap trigger.
    return str(message.get('content') or '')


def _overlap(left, right):
    left = re.sub(r'[\W_]+', '', left)
    right = re.sub(r'[\W_]+', '', right)
    size = SequenceMatcher(None, left, right, autojunk=False).find_longest_match().size
    return size >= 3


def attribution_risk(reply, user_text, history):
    """Spot possible borrowed claims; ordinary reactions don't need another call."""
    if interaction_reply_issue(reply, user_text):
        return True
    clauses = re.split(r'[，。！？!?；;\n]', reply)
    users = [_body(m) for m in history if m.get('role') == 'user'] + [user_text]
    assistants = [_body(m) for m in history if m.get('role') == 'assistant']
    for clause in clauses:
        # Answers such as “刚到第三章呢” omit 我 but still report the bot's
        # own progress. A changed chapter number defeats lexical overlap.
        if re.search(r'^(?:\s|ciallo[~～!！\s]*)*(?:我)?(?:刚(?:刚)?|已经)?'
                     r'(?:[打玩看读刷肝](?:到|完)|刚到).{0,10}(?:章|关|级|剧情)', clause, re.I):
            return True
        # Reactions, offers and figurative jokes alone are not past experiences.
        if re.search(r'我(?:们)?(?:也)?(?:刚|已经|曾|之前|上次|昨天|今天|明天|后天|正在|花|忘|还在|玩|打|看完|买了|去了|建议)', clause):
            if any(_overlap(clause, text) for text in users):
                return True
        # Detect the opposite direction as well: a bot's prior words being
        # attributed to the user. Let the reviewer resolve reported speech.
        if re.search(r'你(?:们)?(?:也)?(?:刚|已经|曾|之前|上次|说|建议|喜欢|花|忘)', clause):
            if any(_overlap(clause, text) for text in assistants):
                return True
    return False


def merge_grounding_messages(history, supplements):
    """Prefer actual conversation roles; deduplicate only unambiguous speakers.

    The culture bridge uses local speaker labels. With duplicate nicknames we
    cannot prove identity, so keep the explicit labels rather than merge people.
    """
    def key(message):
        content = str(message.get('content') or '')
        name, sep, text = content.partition(': ')
        if not sep:
            return message.get('role'), '', content
        return message.get('role'), re.sub(r'（群友\d+）$', '', name), text
    names = {}
    for message in supplements:
        name = key(message)[1]
        names.setdefault(name, set()).add(message['content'].partition(': ')[0])
    actual = {key(m) for m in history}
    extra = [m for m in supplements if key(m) not in actual or len(names[key(m)[1]]) > 1]
    return extra + history
