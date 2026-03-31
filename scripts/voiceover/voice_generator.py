"""
ElevenLabs voice-over generation with automatic script chunking.

Handles long scripts by intelligently chunking them based on sentence boundaries
and ElevenLabs' character limits. Includes retry logic and cost estimation.
"""

import logging
import os
import time
from typing import List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# ElevenLabs API constants
ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
MAX_CHARS_PER_REQUEST = 5000  # ElevenLabs character limit per request


class VoiceGenerator:
    """Generate voice-over audio using ElevenLabs API."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the voice generator.

        Args:
            api_key: ElevenLabs API key. If None, uses ELEVENLABS_API_KEY env var
        """
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ElevenLabs API key not provided. Set ELEVENLABS_API_KEY env var."
            )

        self.headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        self._voices_cache = None
        logger.info("VoiceGenerator initialized")

    def list_voices(self) -> List[dict]:
        """
        List all available voices from ElevenLabs.

        Returns:
            List of voice dictionaries with id, name, category, etc.

        Raises:
            requests.RequestException: If API call fails
        """
        try:
            response = requests.get(
                f"{ELEVENLABS_BASE_URL}/voices",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            self._voices_cache = data.get("voices", [])
            logger.info(f"Retrieved {len(self._voices_cache)} available voices")
            return self._voices_cache
        except requests.RequestException as e:
            logger.error(f"Failed to list voices: {e}")
            raise

    def get_voice_by_name(self, name: str) -> Optional[dict]:
        """
        Get a voice by name.

        Args:
            name: Name of the voice to find

        Returns:
            Voice dictionary or None if not found
        """
        if not self._voices_cache:
            self.list_voices()

        for voice in self._voices_cache:
            if voice["name"].lower() == name.lower():
                return voice

        logger.warning(f"Voice not found: {name}")
        return None

    def _chunk_text(self, text: str, max_chars: int = MAX_CHARS_PER_REQUEST) -> List[str]:
        """
        Split text into chunks based on sentence boundaries.

        Args:
            text: Text to chunk
            max_chars: Maximum characters per chunk

        Returns:
            List of text chunks
        """
        sentences = text.split(". ")
        chunks = []
        current_chunk = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # Add period back if it was removed by split
            if not sentence.endswith("."):
                sentence += "."

            # If single sentence is too long, split by commas
            if len(sentence) > max_chars:
                clauses = sentence.split(", ")
                for clause in clauses:
                    if len(current_chunk) + len(clause) < max_chars:
                        current_chunk += clause + ", "
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.rstrip(", "))
                        current_chunk = clause + ", "
            elif len(current_chunk) + len(sentence) < max_chars:
                current_chunk += sentence + " "
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence + " "

        if current_chunk:
            chunks.append(current_chunk.strip())

        logger.info(f"Chunked text into {len(chunks)} parts")
        return chunks

    def _request_with_retry(
        self,
        method: str,
        url: str,
        max_retries: int = 3,
        **kwargs,
    ) -> requests.Response:
        """
        Make HTTP request with exponential backoff retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            max_retries: Maximum number of retry attempts
            **kwargs: Additional arguments to pass to requests

        Returns:
            Response object

        Raises:
            requests.RequestException: If all retries fail
        """
        for attempt in range(max_retries):
            try:
                if method.upper() == "GET":
                    response = requests.get(url, timeout=30, **kwargs)
                elif method.upper() == "POST":
                    response = requests.post(url, timeout=30, **kwargs)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                if response.status_code == 429:  # Rate limited
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"Rate limited. Waiting {wait_time}s before retry..."
                    )
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()
                return response

            except requests.HTTPError as e:
                # 4xx client errors are permanent — retrying won't help
                if e.response is not None and 400 <= e.response.status_code < 500:
                    logger.error(f"Request failed after {max_retries} attempts: {e}")
                    raise
                wait_time = 2 ** attempt
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{max_retries}). "
                        f"Retrying in {wait_time}s: {e}"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"Request failed after {max_retries} attempts: {e}")
                    raise
            except requests.RequestException as e:
                wait_time = 2 ** attempt
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{max_retries}). "
                        f"Retrying in {wait_time}s: {e}"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"Request failed after {max_retries} attempts: {e}")
                    raise

        raise RuntimeError("Retry logic failed")

    def generate(
        self,
        text: str,
        output_path: str,
        voice_id: Optional[str] = None,
        voice_name: str = "Rachel",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
    ) -> str:
        """
        Generate voice-over for the given text.

        Args:
            text: Text to convert to speech
            output_path: Path to save the MP3 file
            voice_id: ElevenLabs voice ID. If None, uses voice_name
            voice_name: Name of the voice to use (if voice_id not provided)
            stability: Voice stability (0-1)
            similarity_boost: Similarity boost (0-1)

        Returns:
            Path to the generated audio file

        Raises:
            ValueError: If voice not found
            requests.RequestException: If API call fails
        """
        # Get voice ID if not provided
        if not voice_id:
            voice = self.get_voice_by_name(voice_name)
            if not voice:
                raise ValueError(f"Voice not found: {voice_name}")
            voice_id = voice["voice_id"]

        # Create output directory if needed
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Chunk text to avoid size limits
        chunks = self._chunk_text(text)
        audio_parts = []

        logger.info(f"Generating voice-over for {len(chunks)} chunks...")

        for i, chunk in enumerate(chunks, 1):
            logger.info(f"Processing chunk {i}/{len(chunks)} ({len(chunk)} chars)")

            url = f"{ELEVENLABS_BASE_URL}/text-to-speech/{voice_id}"

            payload = {
                "text": chunk,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": stability,
                    "similarity_boost": similarity_boost,
                },
            }

            response = self._request_with_retry(
                "POST",
                url,
                headers=self.headers,
                json=payload,
            )

            if response.status_code != 200:
                logger.error(f"Failed to generate voice for chunk {i}: {response.text}")
                raise requests.RequestException(
                    f"Voice generation failed: {response.text}"
                )

            audio_parts.append(response.content)

        # Write audio to file
        with open(output_path, "wb") as f:
            for audio_data in audio_parts:
                f.write(audio_data)

        logger.info(f"Voice-over saved to {output_path}")
        return output_path

    def estimate_cost(self, text: str) -> dict:
        """
        Estimate the cost of generating voice-over for text.

        ElevenLabs pricing is based on character count.
        As of 2024, pricing is approximately $0.00002 per character for standard voices.

        Args:
            text: Text to estimate cost for

        Returns:
            Dictionary with character_count, chunks, estimated_cost
        """
        char_count = len(text)
        chunks = len(self._chunk_text(text))

        # ElevenLabs pricing (approximate, check their current rates)
        cost_per_char = 0.00002
        estimated_cost = char_count * cost_per_char

        return {
            "character_count": char_count,
            "chunks": chunks,
            "estimated_cost_usd": round(estimated_cost, 4),
            "pricing_note": "Based on ElevenLabs standard rates. Verify current pricing.",
        }


def main():
    """Example usage of VoiceGenerator."""
    try:
        generator = VoiceGenerator()

        # List available voices
        print("Available voices:")
        voices = generator.list_voices()
        for voice in voices[:5]:
            print(f"  - {voice['name']} ({voice['voice_id']})")

        # Generate voice-over
        sample_text = """Welcome to the future of content creation.
        Artificial intelligence is revolutionizing how creators produce videos.
        From script generation to video editing, AI tools are becoming essential
        for modern content creators. Let's explore the best tools available today."""

        print("\nEstimating cost...")
        cost = generator.estimate_cost(sample_text)
        print(f"Character count: {cost['character_count']}")
        print(f"Estimated cost: ${cost['estimated_cost_usd']}")

        print("\nGenerating voice-over...")
        output_file = "./sample_voiceover.mp3"
        generator.generate(
            sample_text,
            output_file,
            voice_name="Rachel",
            stability=0.7,
            similarity_boost=0.75,
        )
        print(f"Voice-over saved to {output_file}")

    except Exception as e:
        logger.error(f"Error: {e}")
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
