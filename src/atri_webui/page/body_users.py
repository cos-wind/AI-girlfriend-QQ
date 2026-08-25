from __future__ import annotations

PART = r"""        <div class="surface">
          <div class="section-head">
            <div><h2>统一用户中心</h2><p class="note">用户、群聊、记忆与互动设置集中管理。亚托莉始终置顶，余弦寄长风其次。</p></div>
            <div class="row"><button class="ghost" onclick="runUserDirectoryRefresh(this)">刷新用户目录</button></div>
          </div>
          <div class="user-directory-integrated-toolbar">
            <strong>QQ 空间连接</strong>
            <span id="directoryQzoneBridgeAuth" class="note">正在检查 QQ 空间登录状态...</span>
            <button class="ghost" onclick="directoryStartQZoneLogin()">登录 QQ 空间</button>
            <button onclick="runUserDirectoryRefresh(this)">刷新好友动态与群聊计划</button>
            <label class="switch-line"><input id="directoryProactiveEnabled" type="checkbox" onchange="saveDirectoryProactiveToggle()">主动消息</label>
            <span id="directoryProactiveState" class="note">正在读取主动消息状态...</span>
          </div>
          <div class="user-directory-integrated-toolbar modality-policy-toolbar">
            <strong>视觉 / 语音权限</strong>
            <label class="switch-line"><input id="directoryVisionAllowlistEnabled" type="checkbox" onchange="saveDirectoryModalityPolicy()">仅允许勾选用户使用视觉模型</label>
            <label class="switch-line"><input id="directoryVoiceAllowlistEnabled" type="checkbox" onchange="saveDirectoryModalityPolicy()">仅允许勾选用户使用语音模型</label>
            <span id="directoryModalityAccessState" class="note">正在读取权限策略...</span>
          </div>
          <div class="toolbar">
            <label>搜索昵称 / 备注 / QQ<input id="userDirectorySearch" placeholder="输入 QQ 号、昵称、备注或群名片" oninput="renderUserDirectory()"></label>
            <label>来源<select id="userDirectorySource" onchange="renderUserDirectory()"><option value="">全部来源</option><option value="memory">记忆</option><option value="qzone">QQ好友</option><option value="qzone_target">QQ动态策略</option><option value="insights">群聊总结</option><option value="modality">视觉/语音权限</option></select></label>
            <label>对象类型<select id="userDirectoryEntityType" onchange="renderUserDirectory()"><option value="all" selected>用户与群聊</option><option value="user">用户</option><option value="group">群聊</option></select></label>
          </div>
          <p class="note" id="userDirectoryStatus">正在读取统一用户目录...</p>
          <div class="scroll user-directory-scroll"><div id="userDirectoryRows" class="user-directory-list"><div class="empty">正在读取...</div></div></div>
        </div>
      </div>

      <div id="test" class="panel">
        <div class="stack">
          <div class="surface">
            <div class="section-head">
              <div><h2>开发者状态与访问入口</h2><p class="note">MaiBot 是独立服务（默认端口 8001），不会被 ATRI WebUI 代替；NapCat Token 仅在本机展示。</p></div>
              <div class="row"><button class="ghost" onclick="loadDeveloper(true)">刷新状态</button></div>
            </div>
            <div id="developerLinks" class="developer-links"><span class="note">正在读取本机服务信息...</span></div>
          </div>
          <div class="surface">
            <div class="section-head">
              <div><h2>实时项目日志</h2><p class="note" id="developerLogHint">每 3 秒读取一次；聊天正文和 Token 不写入统一日志。</p></div>
              <div class="row"><label>级别<select id="developerLogLevel" onchange="loadDeveloperLogs()"><option value="all">全部</option><option value="debug">Debug</option><option value="info">Info</option><option value="warning">Warn</option><option value="error">Error</option></select></label><button class="ghost" onclick="loadDeveloperLogs()">刷新日志</button></div>
            </div>
            <pre id="developerLog" class="log-view">日志加载中...</pre>
          </div>
          <div class="surface">
            <h2>聊天回复测试</h2>
            <textarea id="testText" placeholder="例如：我今天好累，亚托莉你会怎么回？"></textarea>
            <div class="row"><button onclick="testChat()">生成回复</button></div>
            <div class="out" id="testOut"></div>
          </div>
          <div class="surface">
            <div class="section-head">
              <div><h2>语音识别测试</h2><p class="note" id="testVoiceState">读取语音服务状态...</p></div>
              <div class="row"><button class="ghost" onclick="loadVoiceTestState()">刷新状态</button></div>
            </div>
            <div class="row">
              <label>识别语言<select id="testAsrLanguage"><option value="auto">自动检测</option><option value="zh">中文</option><option value="en">English</option><option value="ja">日本語</option></select></label>
              <input id="testAsrFile" type="file" accept=".wav,.flac,.mp3,.ogg,.m4a,.aac,audio/*" onchange="window._recordedAsrFile=null">
              <button onclick="testVoiceRecognition()">识别文件</button>
              <button id="testAsrRecordButton" class="ghost" onclick="startAsrRecording()">开始说话</button>
              <button id="testAsrStopButton" class="ghost" onclick="stopAsrRecording()" disabled>停止并识别</button>
            </div>
            <div class="natural-box" id="testAsrOut">等待选择音频。</div>
          </div>
          <div class="surface">
            <h2>语音合成测试</h2>
            <div class="grid">
              <label>测试文本<input id="testTtsText" value="主人，今天也请让我陪在你身边。"></label>
              <label>语言<select id="testTtsLanguage" onchange="handleVoiceLanguageChange()"><option value="zh">中文</option><option value="en">English</option><option value="ja">日本語</option></select></label>
              <label>情绪<select id="testTtsEmotion"><option value="gentle">温柔</option><option value="neutral">自然</option><option value="happy">开心</option><option value="shy">害羞</option><option value="sad">难过</option><option value="sleepy">困倦</option><option value="serious">认真</option><option value="surprised">惊讶</option></select></label>
              <label>情绪强度<input id="testTtsIntensity" type="range" min="0" max="1" step="0.05" value="0.55"></label>
            </div>
            <div class="row">
              <button id="testTtsTranslateButton" class="ghost" onclick="translateVoiceTestText()">翻译到目标语言</button>
              <label class="inline-check"><input id="testTtsAutoTranslate" type="checkbox" checked>切换语言时自动翻译</label>
              <label class="inline-check"><input id="testTtsStrictQuality" type="checkbox">严格回读验收（更慢）</label>
              <button id="testTtsButton" onclick="testVoiceSynthesis()">生成试听</button>
              <button id="testTtsCompareButton" class="ghost" onclick="testVoiceComparison()">生成 A/B 试听</button>
            </div>
            <p class="note" id="testTtsOut">默认快速试听单个候选；需要验收时勾选“严格回读验收”。A/B 会额外合成第二个候选。</p>
            <div class="voice-compare">
              <div class="voice-result">
                <h3>候选 A</h3>
                <label>语音档案<select id="testTtsProfileA"></select></label>
                <p class="note" id="testTtsOutA">等待生成。</p>
                <audio id="testTtsAudioA" controls></audio>
              </div>
              <div class="voice-result">
                <h3>候选 B</h3>
                <label>语音档案<select id="testTtsProfileB"></select></label>
                <p class="note" id="testTtsOutB">等待生成。</p>
                <audio id="testTtsAudioB" controls></audio>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div id="evaluation" class="panel">
"""
