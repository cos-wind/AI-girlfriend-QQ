from __future__ import annotations

PART = r"""async function loadQQSongs() {
  const list = $('qqMusicList');
  if(!list) return;
  try {
    const data = await api('/api/music/songs');
    list.innerHTML = data.songs.length ? data.songs.map(song=>`
      <div class="music-delivery-song">
        <strong>《${escapeHtml(song.title)}》</strong>
        <div class="memory-meta">${escapeHtml(song.name)} · ${(Number(song.size)/1024/1024).toFixed(1)} MB</div>
      </div>`).join('') : '<p class="note">歌单为空，放入或导入成品歌曲即可点播。</p>';
  } catch(error) { list.textContent = '歌单读取失败：' + error.message; }
}
async function uploadQQSong() {
  const file = $('qqMusicFile').files[0];
  if(!file) return toast('先选择已合成的完整歌曲');
  const state = $('qqMusicState');
  state.textContent = '正在导入歌曲…';
  const form = new FormData(); form.append('file', file);
  try {
    const result = await api('/api/music/upload', {method:'POST', body:form});
    $('qqMusicFile').value = '';
    await loadQQSongs();
    state.textContent = `已导入 ${result.name}，现在可以点歌。`;
  } catch(error) { state.textContent = '导入失败：' + error.message; }
}
"""
