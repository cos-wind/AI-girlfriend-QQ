"""Transport-independent speech client and contracts."""
from .schema import RecordSegment, SynthesisResult, TranscriptionResult, VoicePromptContext, VoiceRequest
from .client import SpeechServiceClient, SpeechServiceError
from .segmentation import split_spoken_text, spoken_unit_count
