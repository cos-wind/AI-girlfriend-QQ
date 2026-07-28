# ATRI v2Pro corpus training

## Dataset

- Source: local user-provided ATRI voice corpus.
- Label file: `.speaker.list`.
- Labelled clips: 1,936.
- Training split: 1,765 clips, 2.1591 hours.
- Held-out split: 85 clips, 0.0939 hours.
- Rejected: 86 clips.
- Filters: 0.8-12.0 seconds, at least 3 text characters, mono PCM16,
  -45 to -6 dBFS RMS, and no more than 0.5% clipped samples.

The split and per-file hashes are stored outside the repository at:

```text
D:\AtriModels\voice\training\atri-official-v2pro-curated\corpus-audit.json
```

## Training

- Engine: GPT-SoVITS v2Pro.
- Base GPT: official `s1v3.ckpt`.
- Base SoVITS generator and discriminator: official v2Pro weights.
- Batch size: 2.
- FP16 and gradient checkpointing: enabled.
- Epochs: 4.
- Checkpoints: saved after every epoch.

Run individual stages with:

```powershell
data\runtime\gpt-sovits\.venv\Scripts\python.exe `
  tools\voice\train_atri_corpus_v2pro.py --stage audit

data\runtime\gpt-sovits\.venv\Scripts\python.exe `
  tools\voice\train_atri_corpus_v2pro.py --stage features

data\runtime\gpt-sovits\.venv\Scripts\python.exe `
  tools\voice\train_atri_corpus_v2pro.py --stage semantics

data\runtime\gpt-sovits\.venv\Scripts\python.exe `
  tools\voice\train_atri_corpus_v2pro.py --stage train-sovits `
  --sovits-epochs 4 --batch-size 2
```

## Selection

The benchmark uses six unseen Japanese, Chinese, and English sentences and
twenty held-out official ATRI clips for the speaker centroid. It uses the same
seeds and style parameters as the production voice service.

| Candidate | Mean speaker similarity | Mean ASR error rate |
| --- | ---: | ---: |
| Curated epoch 1 | 0.8617 | 0.0389 |
| Existing VoidShine epoch 8 | 0.8379 | 0.0749 |
| Curated epoch 2 | 0.8518 | 0.0722 |
| Curated epoch 3 | 0.8568 | 0.2076 |
| Curated epoch 4 | 0.8519 | 0.1396 |

Epoch 1 is registered as `atri-official-v2pro-curated`. Later epochs remain
available as rollback and comparison artifacts but are not registered.

The complete benchmark report and generated WAV files are stored at:

```text
D:\AtriModels\voice\training\atri-official-v2pro-curated\benchmark
```
