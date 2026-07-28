# ATRI voice model candidate audit

Audit date: 2026-07-22

The TTS inventory began as a metadata-only audit. The two approved TTS candidates and the isolated ASR comparison candidates have since been downloaded with pinned revisions and local integrity manifests; unlicensed audio datasets were not downloaded.

## ASR comparison status

- Default: SenseVoiceSmall with local FSMN-VAD, 16kHz mono preprocessing, and a hot-reloaded project lexicon.
- Candidate: `FunAudioLLM/Fun-ASR-Nano-2512`, pinned at `272c57b82523ada6fd87095e955f8e29100979ab`.
- Candidate: `mobiuslabsgmbh/faster-whisper-large-v3-turbo`, pinned at `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`.
- Candidate weights live under `D:\本地大模型\models\AI_ATRI\voice\asr`; their Python packages live under `data\runtime\asr-candidate-runtime`.
- The six-sample tri-language screen selected SenseVoice as the online engine. The other two candidates remain available for future real-microphone evaluation and are not loaded into the 8GB GPU during normal operation.

## Recommended evaluation order

### A. 2DIPW/ATRI_GPT-SoVITS

- Source: https://huggingface.co/2DIPW/ATRI_GPT-SoVITS
- Engine: GPT-SoVITS; custom GPT and SoVITS weights are both present.
- Declared license: CC BY-NC-SA 4.0, with additional non-commercial/content restrictions.
- Declared training source: `ATRI -My Dear Moments-` game resources.
- Declared dataset duration: 112 minutes.
- Files:
  - `atri-e10.ckpt`: 155,087,613 bytes; SHA-256 `def59c3ab387e2c184b051c944760c7a0ca5b4b18fcbf249ebcd7db52b37cf77`
  - `atri_e25_s5250.pth`: 84,932,551 bytes; SHA-256 `317642ed2f25fb6160def963af4360cea42bf93f6637c1b972cac62aee610fdc`
  - Ten Japanese WAV reference clips with matching transcript-style filenames.
- Assessment: best first fidelity candidate because it has the largest declared ATRI-specific dataset and a complete GPT/SoVITS pair.
- Open question: the GPT-SoVITS generation/version is not declared and must be detected in quarantine before loading.

### B. VoidShine/atri-sovits

- Source: https://huggingface.co/VoidShine/atri-sovits
- Engine: declared GPT-SoVITS v2Pro.
- Declared capability: Japanese, Chinese, and English synthesis.
- Declared license: AGPL-3.0 plus personal/research-only and no-impersonation notice.
- Files:
  - `ATR_e8_s3952.pth`: 134,936,883 bytes; SHA-256 `cdf42ec9f35654a92039b7832becfc9f0f4b111b84f4c5d5266bbac219d0d46a`
  - `ref_audio.wav`: 316,654 bytes; SHA-256 `1922a8ca728643b2e62166bc3ffcd94253bf9faac2c5aa3af0fd9218d37f103c`
  - `api_atri.py`: FastAPI `/health`, `/tts`, and `/tts/stream` adapter.
- Assessment: best second candidate for tri-language testing, but it only contains a custom SoVITS weight and relies on a generic GPT checkpoint.
- Open question: the model card calls it v2Pro while instructing use of `s1v3.ckpt`; compatibility must be verified rather than assumed.

## Voice-conversion comparison candidates

### 2DIPW/ATRI_SoVITS

- Source: https://huggingface.co/2DIPW/ATRI_SoVITS
- Engine: So-VITS 4.0/4.0v2 voice conversion, not direct text-to-speech.
- Declared license: CC BY-NC-SA 4.0 with additional restrictions.
- Declared data: 49/79 minutes of game resources.
- Main weight: `G_39200.pth`, 542,178,141 bytes.
- Assessment: useful only for a base-TTS-to-voice-conversion comparison; not the primary architecture.

### gb16001/sovits4.1_ATRI

- Source: https://huggingface.co/gb16001/sovits4.1_ATRI
- Engine: So-VITS 4.1 with diffusion and k-means components.
- Declared license: AGPL-3.0.
- Main files: 627.9 MB generator, 220.9 MB diffusion model, and 31.0 MB k-means model.
- Assessment: singing/voice conversion candidate, not direct conversational TTS.

### AppleAndA/ATRI_RVC_Models

- Source: https://huggingface.co/AppleAndA/ATRI_RVC_Models
- Engine: RVC v2 voice conversion.
- License: not declared.
- Inference files: `ATRI_e500_s206500.pth` and a 534 MB FAISS index; the repository also contains large training checkpoints.
- Assessment: do not install unless the author adds clear usage terms. RVC would also require a separate multilingual base TTS engine.

## Audio dataset findings

### AppleAndA/ATRI_Voice_Datasets

- Source: https://huggingface.co/datasets/AppleAndA/ATRI_Voice_Datasets
- Contents: 1,303 WAV files, approximately 0.59 GB.
- License: not declared; model card contains no provenance or usage terms.
- Decision: do not download or train from it.

### Yusen/Sovits_ATRI

- Source: https://huggingface.co/datasets/Yusen/Sovits_ATRI
- Contents: 25 WAV files plus precomputed So-VITS features, approximately 0.12 GB total.
- License: `other`, with no actual terms in the model card.
- Decision: do not download or train from it.

## Download gate

Before any candidate is downloaded:

1. Pin the repository revision and expected files.
2. Download into `D:\本地大模型\models\AI_ATRI\voice\candidates\<candidate>`.
3. Verify file size and SHA-256 against this inventory.
4. Treat `.pth` and `.ckpt` as untrusted serialized data and inspect them in the isolated voice runtime only.
5. Never execute repository-provided Python files without static review.
6. Run fixed Japanese, Chinese, and English test sentences before enabling QQ output.

## Current recommendation

Evaluate `2DIPW/ATRI_GPT-SoVITS` first and `VoidShine/atri-sovits` second. Do not use the public audio datasets for retraining because their usage rights are missing or unclear.
