from __future__ import annotations

PART = r"""        <div id="evaluationDashboardPanel" class="insight-subpanel active">
          <div class="surface">
              <div class="section-head">
              <div><h2>回复质量评测</h2><p class="note">系统回复完成后实时进入异步评测队列；评测模型从“模型”页面的聊天模型档案中选择。</p></div>
              <div class="row"><label>评测模型<select id="evaluationModelProfile" onchange="saveEvaluationModelProfile()"><option value="">跟随当前聊天模型</option></select></label><label>能力分类<select id="evaluationModelType" onchange="loadEvaluation(true)"><option value="">全部模型</option><option value="chat">聊天模型</option><option value="vision">视觉模型</option><option value="voice">语音模型</option></select></label><button class="ghost" onclick="loadEvaluation(true)">刷新</button></div>
            </div>
            <div id="evaluationState" class="natural-box">正在读取评测状态...</div>
            <div id="evaluationStats" class="stat-grid"></div>
            <div id="evaluationModelStats" class="evaluation-model-grid"></div>
            <div id="evaluationDeliveryStats" class="delivery-grid"></div>
            <div id="evaluationDimensions" class="score-grid"></div>
          </div>
          <div class="surface">
            <div class="section-head"><div><h2>整体评分趋势</h2><p class="note">质量指数 = 中位数 + 低分尾部的加权结果；阴影表示 P25–P75，避免日均分把波动抹平。</p></div></div>
            <svg id="evaluationTrend" class="trend-chart" viewBox="0 0 900 240" role="img" aria-label="评测趋势图"></svg>
            <div id="evaluationTrendDetails" class="scroll" style="margin-top:12px"><div class="empty">暂无按日明细。</div></div>
          </div>
          <div class="split">
            <div class="surface">
              <h2>问题定位</h2>
              <div id="evaluationIssues" class="entry-list"><div class="empty">暂无问题。</div></div>
            </div>
            <div class="surface">
              <h2>筛选评测记录</h2>
              <div class="toolbar">
                <label>状态<select id="evaluationStatus" onchange="loadEvaluationRecords()"><option value="">全部</option><option value="completed">已完成</option><option value="queued">排队中</option><option value="running">评测中</option><option value="failed">失败</option></select></label>
                <label>维度<select id="evaluationDimension" onchange="loadEvaluationRecords()"><option value="">全部维度</option><option value="relevancy">相关性</option><option value="accuracy">准确性</option><option value="completeness">完整性</option><option value="coherence">连贯性</option><option value="faithfulness">忠实度</option><option value="hallucination">无幻觉程度</option></select></label>
                <label>总分不高于<input id="evaluationMaxScore" type="number" min="0" max="5" step="0.5" onchange="loadEvaluationRecords()"></label>
                <label>搜索<input id="evaluationQuery" placeholder="问题 / 回答 / 会话"></label>
                <button class="ghost" onclick="loadEvaluationRecords()">查询</button>
                <button class="secondary" onclick="retryFailedEvaluations()">批量重试失败</button>
              </div>
            </div>
          </div>
          <div class="surface">
            <div class="scroll"><table><thead><tr><th>时间 / 状态</th><th>问题与回答</th><th>各维度</th><th>总分</th><th>操作</th></tr></thead><tbody id="evaluationRows"><tr><td colspan="5" class="empty">读取中...</td></tr></tbody></table></div>
            <div id="evaluationDetail" class="natural-box" style="margin-top:12px">点击“详情”查看评分理由和检索上下文。</div>
          </div>
        </div>

      </div>

      <div id="advanced" class="panel">
"""
