"""Characterization test for chunking (Unit 8).

Chatterbox single-shot TTS caps ≈40 s of audio; anything longer is
silently truncated. The client's ``_chunk_text`` splits on sentence
boundaries to keep each chunk under the cap. This test guards against
regressions to the chunking behavior that would reintroduce the
40-second-silent-truncation bug (commit 7841205).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from voiceover.chatterbox_generator import ChatterboxVoiceGenerator


class ChunkTextTests(unittest.TestCase):
    def test_short_text_is_a_single_chunk(self):
        text = "This is one sentence."
        chunks = ChatterboxVoiceGenerator._chunk_text(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text)

    def test_long_text_splits_at_sentence_boundaries(self):
        # Build a script that exceeds the per-chunk cap. Each sentence
        # is ~30 chars so we need ~15 sentences to comfortably exceed
        # the ~380-char default chunk cap.
        sentences = [f"Sentence number {i:02d} fits here." for i in range(40)]
        text = " ".join(sentences)
        chunks = ChatterboxVoiceGenerator._chunk_text(text)
        self.assertGreater(len(chunks), 1, "long text should split")
        # Each chunk must respect the default max.
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 380)
        # Every sentence shows up exactly once across the chunk set.
        reassembled = " ".join(chunks)
        for sent in sentences:
            self.assertIn(sent, reassembled)

    def test_long_form_script_regression(self):
        """A 5-minute-ish script (~700-900 words) must split into enough
        chunks that each fits well under the 40-second TTS cap."""
        base = [
            "The hallway ended where it shouldn't.",
            "I counted the doors a second time.",
            "Each one was identical to the last.",
            "The fluorescent hum shifted frequency.",
            "I stopped walking and listened.",
            "Somewhere behind me a door closed.",
            "I had not passed any open doors.",
            "I did not turn around.",
            "The exit sign at the far end was dark.",
            "It had not been dark a moment ago.",
        ]
        text = " ".join(base * 12)  # ~120 sentences
        chunks = ChatterboxVoiceGenerator._chunk_text(text)

        self.assertGreater(
            len(chunks), 4,
            "5-min script must split into several chunks to survive "
            "40-second TTS cap",
        )
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 380)

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(ChatterboxVoiceGenerator._chunk_text(""), [])
        self.assertEqual(ChatterboxVoiceGenerator._chunk_text("   "), [])

    def test_single_sentence_longer_than_cap_is_force_split(self):
        """A pathological single sentence longer than the cap must still
        be split (on comma or word boundary) so no chunk exceeds the cap."""
        giant = (
            "This is one very long run-on sentence that never stops "
            "going, because the speaker refuses to breathe, and every "
            "comma is just another clause piled on top of another, and "
            "every subordinate phrase adds yet more words to the already "
            "absurd pileup of a narrator refusing punctuation, and the "
            "chunker must find a place to break it even when no period "
            "appears for hundreds of characters at a stretch."
        )
        chunks = ChatterboxVoiceGenerator._chunk_text(giant)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 380)


if __name__ == "__main__":
    unittest.main(verbosity=2)
