from __future__ import annotations

PART = r"""        <div class="settings-section accordion-section">
          <div class="section-head">
            <div>
              <h3>QQ 点歌素材库</h3>
              <p class="note">QQ 点歌只从 <span class="mono">data/music</span> 按文件名匹配歌曲，并把对应完整文件作为 QQ 语音发送。放入或导入成品后即可点歌。</p>
            </div>
            <div class="row"><button class="ghost" onclick="loadQQSongs()">刷新素材库</button></div>
          </div>

          <div class="music-delivery-grid">
            <div class="music-import-box">
              <strong>导入完整音乐</strong>
              <span class="param-help">支持 WAV、FLAC、MP3、OGG、M4A、AAC、OPUS；歌名默认使用文件名。</span>
              <input id="qqMusicFile" type="file" accept=".wav,.flac,.mp3,.ogg,.m4a,.aac,.opus,audio/*">
              <div class="row"><button class="ghost" onclick="uploadQQSong()">导入完整音乐</button></div>
              <p id="qqMusicState" class="note">目录中的完整歌曲会直接进入 QQ 点歌清单。</p>
            </div>
            <div>
              <strong>可点播的完整歌曲（QQ 实际发送来源）</strong>
              <div id="qqMusicList" class="music-delivery-list"><p class="note">正在读取完整歌曲…</p></div>
            </div>
          </div>

        </div>
"""
