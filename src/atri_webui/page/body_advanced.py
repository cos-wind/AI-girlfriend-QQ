from __future__ import annotations

PART = r"""        <div class="section-head">
          <div>
            <h2>高级配置</h2>
            <p class="note">集中管理回复策略、主动互动、联网搜索 API、OCR 与视频抽帧参数。聊天与视觉模型的接口档案在“模型”页面配置。</p>
          </div>
        </div>
        <div class="settings-section accordion-section">
          <div class="section-head">
            <div>
              <h3>回复策略与主动互动</h3>
              <p class="note">私聊按好感度分档、群聊按活跃度分档，决定回不回、回多快、回多长，也决定多久主动找一次。数值分档在下方通栏面板里切换；单个对象的开关仍然在「用户中心」里逐个设置，这里的「对象例外」和它共用同一份名单。</p>
            </div>
            <div class="row">
              <button class="ghost" onclick="loadProactive()">刷新状态</button>
              <button onclick="saveReplyStrategy(this)">保存全部配置</button>
            </div>
          </div>

          <div class="tier-workbench proactive-block">
            <div class="section-head">
              <div>
                <h3>数值分档</h3>
                <p class="note">同一张表同时决定「收到消息怎么回」和「多久主动找一次」。好感范围只填一次，切换面板只是换一个查看和修改的维度。表格从上往下就是门槛：数值落在哪一档就按那一档执行，档位停用即不回复。</p>
              </div>
              <div class="row">
                <button class="ghost" onclick="resetReplyStrategyCounters(this)">重置计数</button>
              </div>
            </div>
            <div class="tier-tabs" role="tablist">
              <button type="button" class="tier-tab active" data-tier-tab="user" onclick="showTierPane('user')">用户分档<span class="tier-tab-badge"></span></button>
              <button type="button" class="tier-tab" data-tier-tab="group" onclick="showTierPane('group')">群聊分档</button>
            </div>
            <div class="tier-pane active" id="tierPaneUser">
              <p class="note">按对方好感度命中一个档位。取消勾选“启用”表示这一档整体停用（这就是好感度门槛）。「目标字数」和「最多分条」只作为给模型的软引导（“约多少字”），不是死命令；填 0 表示不限制，留空表示保持原值。回复频率（每小时/每日上限、冷却）已移除——回不回只由对象模式和档位启用决定。</p>
              <div class="scroll tier-table-scroll">
                <table class="tier-table">
                  <thead>
                    <tr class="tier-group-head">
                      <th class="tier-col-stage"></th>
                      <th class="tier-col-switch"></th>
                      <th class="tier-col-range"></th>
                      <th class="tier-group tier-group-reply" colspan="2">被动回复（对方先说话时）</th>
                      <th class="tier-group tier-group-proactive" colspan="2">主动发起（亚托莉先说话）</th>
                    </tr>
                    <tr>
                      <th class="tier-col-stage">档位</th>
                      <th class="tier-col-switch">启用</th>
                      <th class="tier-col-range">好感范围</th>
                      <th class="tier-group-reply">目标字数</th>
                      <th class="tier-group-reply">最多分条</th>
                      <th class="tier-group-proactive">随机间隔（小时）</th>
                      <th class="tier-group-proactive">每日上限</th>
                    </tr>
                  </thead>
                  <tbody id="affectionTierRows"></tbody>
                </table>
              </div>
              <p class="note">右两列是主动消息自己的参数：随机间隔表示「多久主动找一次」的上下限，每日上限填 0 表示这一档不主动发消息。</p>
            </div>
            <div class="tier-pane" id="tierPaneGroup">
              <p class="note">按群活跃度命中一个档位。取消勾选“启用”表示该活跃度区间不再回复（也就是群聊的活跃度门槛）。「目标字数」只作为给模型的软引导，不是死命令。回复频率（每小时/每日上限、冷却、连聊上限）已移除——回不回只由对象模式（smart / mention / silence）和档位启用决定。右两列是主动消息的参数：群聊主动消息按群活跃度命中同一档位，用这一档的随机间隔和每日上限。</p>
              <div class="scroll tier-table-scroll">
                <table class="tier-table tier-table-group">
                  <thead>
                    <tr class="tier-group-head">
                      <th class="tier-col-stage"></th>
                      <th class="tier-col-switch"></th>
                      <th class="tier-col-range"></th>
                      <th class="tier-group tier-group-reply" colspan="1">被动回复（群消息触发时）</th>
                      <th class="tier-group tier-group-proactive" colspan="2">主动发起（亚托莉先在群里说话）</th>
                    </tr>
                    <tr>
                      <th class="tier-col-stage">档位</th>
                      <th class="tier-col-switch">启用</th>
                      <th class="tier-col-range">活跃度范围</th>
                      <th class="tier-group-reply">目标字数</th>
                      <th class="tier-group-proactive">随机间隔（小时）</th>
                      <th class="tier-group-proactive">每日上限</th>
                    </tr>
                  </thead>
                  <tbody id="replyActivityTierRows"></tbody>
                </table>
              </div>
              <div class="tier-switches">
                <label class="switch-line"><input id="proactiveGroupEnabled" type="checkbox">启用活跃群聊</label>
              </div>
              <p class="note">「启用活跃群聊」是群聊主动消息的总开关；「主动发起」的每日上限填 0 表示这一档不在群里主动说话（和左边被动回复的每日上限是两件事）。</p>
            </div>
          </div>

          <div class="split">
            <div class="proactive-block">
              <h3>主动发起</h3>
              <p class="note" id="proactiveFeatureState">读取中...</p>
              <div class="grid">
                <label class="switch-line"><input id="proactiveEngineEnabled" type="checkbox">启用新版主动调度器</label>
                <label class="switch-line"><input id="proactiveEnabled" type="checkbox">允许发送主动消息</label>
                <label class="switch-line"><input id="proactiveOwnerOnly" type="checkbox">私聊仅限主人</label>
                <label class="switch-line"><input id="proactiveUseAi" type="checkbox">优先由聊天模型生成</label>
                <label class="switch-line"><input id="proactiveGuidedTopics" type="checkbox">话题使用引导式开场</label>
                <label>时区<input id="proactiveTimezone" value="Asia/Shanghai"></label>
                <label>免打扰开始<input id="proactiveQuietStart" type="time"></label>
                <label>免打扰结束<input id="proactiveQuietEnd" type="time"></label>
                <label>检查间隔（秒）<input id="proactiveCheckSeconds" type="number" min="15" max="3600"></label>
                <label>连续未回复倍率<input id="proactiveBackoff" type="number" min="1" max="3" step="0.1"></label>
                <label>参考最近消息数<input id="proactiveHistoryLimit" type="number" min="0" max="20"></label>
                <label>主动消息最大字数<input id="proactiveMaxChars" type="number" min="20" max="240"></label>
              </div>
              <p class="note">私聊多久主动找一次由「用户分档」的随机间隔决定；群聊的开关在上面的「主动发起」里，门槛、间隔与单群上限在「群聊分档」页签里配。免打扰时段内不会发送。</p>
            </div>
            <div class="stack">
              <div class="proactive-block">
                <h3>通用回复设置</h3>
                <div class="grid" id="configForm"></div>
                <p class="note">语音概率仅影响普通消息；用户明显难受或疲惫时会提高到至少 70%。明确要求语音和回应用户语音不受该概率限制。</p>
                <div class="row">
                  <button onclick="saveConfig()">保存回复配置</button>
                  <button class="ghost" onclick="loadConfig()">放弃页面修改</button>
                </div>
              </div>
              <div class="proactive-block">
                <h3>主动消息内容权重</h3>
                <p class="note">按权重抽取内容类型；权重为 0 表示禁用该类型。早安和晚安只在对应时段参与抽取。</p>
                <h4 class="weight-title">私聊</h4>
                <div class="weight-grid weight-grid-compact" id="proactiveWeights"></div>
                <h4 class="weight-title">群聊</h4>
                <div class="weight-grid weight-grid-compact" id="proactiveGroupWeights"></div>
              </div>
            </div>
          </div>

          <div class="proactive-block">
            <h3>对象例外</h3>
            <details>
              <summary>什么时候需要加例外？</summary>
              <p class="note">没列在这里的群聊按「通用回复设置」里的回复模式走。列进来之后，群聊可以在三种模式里选一个：<br>
                <strong>smart</strong> —— 被 @ 或命中触发词就回；被 @ 之后 5 分钟内这个人再说话不用重新 @（就是"续聊窗口"）。<br>
                <strong>mention</strong> —— 每一轮都要 @ 才回，续聊窗口也不放行，入群欢迎这类事件同样不发。<br>
                <strong>silence</strong> —— 沉默，只观察不回复（消息仍进记忆和总结）。<br>
                私聊对象没有 @ 的概念，仍用「跟随分档 / 强制允许 / 禁止回复 / 只记录」这四种。每小时的数字留空表示跟随分档，填 0 表示这一项不限制。「用户中心」里逐个开关的“允许聊天”写的也是这张名单。</p>
            </details>
            <div class="grid">
              <label>对象 QQ / 群号<input id="replyExceptionNewObject" type="number" min="1" step="1" placeholder="纯数字"></label>
              <label>对象类型<select id="replyExceptionNewKind">
                <option value="user">用户（私聊）</option>
                <option value="group">群聊</option>
              </select></label>
            </div>
            <div class="row"><button onclick="addReplyExceptionObject()">新增例外对象</button></div>
            <div class="scroll"><table>
              <thead><tr><th>对象</th><th>类型</th><th>模式</th><th>每小时</th><th>每日</th><th>操作</th></tr></thead>
              <tbody id="replyExceptionRows"></tbody>
            </table></div>
          </div>

          <div class="row">
            <button onclick="saveReplyStrategy(this)">保存全部配置</button>
            <button class="ghost" onclick="loadReplyStrategy(); loadProactive();">放弃页面修改</button>
          </div>
          <p class="note">「数值分档」被回复策略和主动互动共用，所以这里保存的是一整份：回复上限、主动间隔、门槛和权重会一起落盘，不会只写一半。主动消息的文案预览已并入「测试」页的聊天回复测试。</p>
        </div>
        <div class="settings-section">
          <div class="section-head">
            <div>
              <h3>本地服务（手动启动）</h3>
              <p class="note">三个服务都不随桌宠 / NapCat 自动启动，只有在这里点击启动后才可用；不启动时不会产生任何空间网页请求，也不会刷新空间登录态。语音服务运行中时，同一个按钮会变成「停止语音服务」（会直接结束 8790 进程，正在进行的合成会被掐断）。运行状态统一显示在上方「运行状态」，卡片里不再重复显示。</p>
            </div>
          </div>
          <div class="row service-switch">
            <button id="voiceServiceStartButton" onclick="toggleVoiceService(this)">启动语音服务</button>
            <button id="musicWorkbenchStartButton" onclick="startMusicWorkbench(this)">启动歌曲工作台</button>
            <button class="ghost" onclick="openMusicWorkbench()">打开歌曲工作台</button>
            <button id="qzoneBridgeStartButton" onclick="startQZoneBridge(this)">启动 QQ 空间 Bridge</button>
            <button class="danger" id="qzoneBridgeStopButton" onclick="stopQZoneBridge(this)">停止 QQ 空间 Bridge</button>
          </div>
          <p class="note">歌曲工作台（<span class="mono">AI_music</span>）是独立项目：导唱转换、人声分离、模型推理与后期混音都在它自己的界面里完成，本项目只负责启动与跳转。</p>
        </div>
"""
