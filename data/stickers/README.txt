把你的本地表情包图片放在这里。

推荐文件夹：
- happy：开心、夸奖、日常轻松
- comfort：安慰、摸摸头
- sad：想哭、低落、失落、心碎
- angry：生气、火大、红温、替主人抱不平
- tired：累了、困了
- proud：高性能、得意
- confused：没懂、纠错
- speechless：无语、嫌弃、沉默、麻了
- surprised：震惊、真的假的、不会吧
- awkward：尴尬、社死、难绷
- teasing：调侃、逗你、嘴硬、轻松互怼
- shy：害羞、亲密表达
- affection：抱抱、贴贴、陪陪我
- miss：想你、等你、有没有想我
- care：喝水、吃药、注意身体、别硬撑
- thanks：谢谢、感谢、被夸
- sorry：道歉、原谅、给台阶
- encourage：加油、冲呀、坚持、打起精神
- thinking：纠结、要不要、该不该、选择困难
- celebrate：庆祝、完成、搞定、通过
- food：吃饭相关
- goodnight：晚安
- pout：傲娇、生气、被冷落、萝卜子
- unsorted：聊天记录里暂时判断不出情绪的表情，默认不会自动发送

支持格式：png、jpg、jpeg、gif、webp。

情绪规则在 emotion_map.json 里查看。现在发送图片时只会从同情绪文件夹挑选，不会再用 happy 图片兜底到 comfort 场景。

自定义触发词在 triggers.json 里改。
例如：
"摸摸头": "comfort"
表示用户消息里出现“摸摸头”时，会优先从 comfort 文件夹选一张图片。

也支持网页图片 URL，但建议只填你确认可用、允许使用的图片地址：

"web_images": {
  "happy": ["https://example.com/happy.webp"]
}

注意：机器人不会自动抓取全网图片，避免误发侵权、失效或不安全内容。

自动归档聊天记录表情：

你或别人发给亚托莉的图片/表情包，如果 NapCat 消息里带可下载 URL，会自动保存到：

_chat_history\<emotion>

例如：

_chat_history\happy
_chat_history\comfort
_chat_history\pout
_chat_history\unsorted

能判断情绪的图片会自动加入对应情绪库。判断不出来的会先进 _chat_history\unsorted，不会自动发送；你确认含义后，把图片移动到 happy、comfort 等正确文件夹即可。

网络精选表情：

我会把来源清楚、适合兜底的开源表情放在：

_curated\<emotion>

这个文件夹也可以手动添加。优先级是：你手动放入的 <emotion> 文件夹 > _curated > _chat_history 同情绪 > _online_default。

默认联网表情缓存：

我已经从开源 Noto Emoji 下载了一套默认图，放在：

_online_default\<emotion>

这些图是兜底用的，不需要聊天时实时联网。

如果某个情绪文件夹没有图片，亚托莉会自动发送 QQ 内置表情作为兜底。
默认大约 32% 的回复会尝试带一个表情，并且有 120 秒冷却，不会连续刷屏。

可以在 triggers.json 里调节 QQ 内置表情 ID：

"emotion_faces": {
  "happy": [14, 21, 76]
}
