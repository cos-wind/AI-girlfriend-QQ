from __future__ import annotations

PART = r"""        <div class="section-head">
          <div>
            <h2>Minecraft 女仆桥接测试</h2>
            <p class="note">独立测试区：后台通过本机桥接服务控制 UMU Little Maid，不会登录第二个账号，也不会向服务器发送任意命令。</p>
          </div>
          <div class="row">
            <button class="ghost" onclick="loadMinecraft()">刷新状态</button>
          </div>
        </div>
        <div class="minecraft-grid">
          <div class="stack">
            <div class="surface">
              <h2>连接配置</h2>
              <label class="switch-line"><input id="minecraftEnabled" type="checkbox">允许亚托莉控制自己的女仆</label>
              <label>本地桥接地址<input id="minecraftBridgeUrl" value="http://127.0.0.1:8792"></label>
              <div class="row">
                <button onclick="saveMinecraftConfig()">保存配置</button>
                <button class="ghost" onclick="loadMinecraft()">放弃修改</button>
              </div>
              <p class="note">只允许 127.0.0.1 或 localhost。先运行 AI_game 中的 <span class="mono">scripts\start_bridge.ps1</span>，再启动测试 Minecraft。</p>
            </div>
            <div class="surface">
              <h2>安全边界</h2>
              <div class="stack note">
                <div>• 只识别当前玩家拥有的 UMU 女仆。</div>
                <div>• 切换模式时女仆需在 4.5 格内，且玩家主手为空。</div>
                <div>• 只允许跟随、待命、自由、停止和状态刷新。</div>
                <div>• 守卫、治疗、农夫等职业仍由女仆装备决定。</div>
              </div>
            </div>
          </div>
          <div class="stack">
            <div class="surface">
              <div class="section-head">
                <div>
                  <h2>实时状态</h2>
                  <p class="note" id="minecraftStatusText">尚未连接桥接服务。</p>
                </div>
              </div>
              <div id="minecraftStatusCards" class="minecraft-status"></div>
              <label>控制对象<select id="minecraftMaidSelect" onchange="renderMinecraftMaidSelection()"></select></label>
              <div class="minecraft-command-grid">
                <button onclick="sendMinecraftCommand('follow')">跟随</button>
                <button class="secondary" onclick="sendMinecraftCommand('wait')">待命</button>
                <button class="ghost" onclick="sendMinecraftCommand('free')">自由活动</button>
                <button class="danger" onclick="sendMinecraftCommand('stop')">停止</button>
              </div>
              <div id="minecraftMaidList" class="minecraft-maids"><div class="note">等待女仆遥测。</div></div>
            </div>
            <div class="surface">
              <h2>最近执行结果</h2>
              <div class="out" id="minecraftCommandOut">尚未执行测试命令。</div>
            </div>
          </div>
        </div>
      </div>

      <div id="advanced" class="panel">
"""
