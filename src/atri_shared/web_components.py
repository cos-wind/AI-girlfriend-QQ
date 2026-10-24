"""Markup shared by WebUI and the local desktop console."""

MODEL_EDITOR = r'''          <div class="surface" id="modelProfileEditor">
            <h2 id="profileFormTitle">新建模型档案</h2>
            <p class="model-feedback" id="modelFillFeedback"></p>
            <input id="profileId" type="hidden">
            <div class="preset-panel">
              <h3>从厂商模型库填入</h3>
              <div class="form-grid">
                <label>厂商<select id="providerPreset" onchange="selectProviderPreset()"></select></label>
                <label>模型<select id="providerModelPreset" onchange="selectProviderModelPreset()"></select></label>
              </div>
              <div class="row">
                <button class="ghost" onclick="applySelectedProviderModel()">填入到下方档案</button>
              </div>
              <p class="note">这里只负责自动填接口地址、模型名和推荐参数；保存、启用仍由你手动确认。</p>
            </div>
            <h3>档案参数</h3>
            <div class="form-grid">
              <label>档案名称<input id="profileName" placeholder="例如：DeepSeek 官方"></label>
              <label>用途<select id="profileModelType">
                <option value="chat">聊天模型</option>
                <option value="vision">视觉模型</option>
                <option value="embedding">向量模型</option>
              </select></label>
              <label>服务商<input id="profileProvider" placeholder="例如：DeepSeek / Ollama / OpenAI兼容"></label>
              <label>接口地址<input id="profileBaseUrl" placeholder="https://api.deepseek.com/v1"></label>
              <label>模型名称<input id="profileModel" placeholder="deepseek-v4-flash"></label>
              <label>API Key<input id="profileApiKey" type="password" placeholder="已保存时留空可保持原值"></label>
              <label>温度<input id="profileTemperature" type="number" min="0" max="2" step="0.01" value="0.65"></label>
              <label>重复惩罚<input id="profileFrequencyPenalty" type="number" min="0" max="2" step="0.01" value="0.35"></label>
              <label>最大输出<input id="profileMaxTokens" type="number" min="32" max="4096" step="1" value="260"></label>
            </div>
            <div class="row">
              <button onclick="saveProfile()">保存档案</button>
              <button class="ghost" onclick="activateSelectedProfile()">启用档案</button>
              <button class="secondary" onclick="newProfile()">新建空档案</button>
              <button class="danger" onclick="deleteSelectedProfile()">删除档案</button>
            </div>
          </div>'''
