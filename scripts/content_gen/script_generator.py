"""
AI-powered script generation for social media content.

Supports multiple LLM backends (Claude via Anthropic, GPT via OpenAI) with
detailed system prompts for long-form, short-form, and Twitter thread content.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import anthropic
import openai

logger = logging.getLogger(__name__)


class ScriptGenerator:
    """Generate optimized scripts for various social media formats."""

    # System prompts for different content types
    SYSTEM_LONG_FORM = """You are an expert video scriptwriter specializing in engaging long-form content.
Create compelling, well-structured scripts that:
- Hook viewers in the first 10 seconds
- Maintain pacing and energy throughout
- Include natural transitions between sections
- End with a strong call-to-action
- Are optimized for the target niche and audience

Format your response as a JSON object with keys: title, hook, script, description, tags"""

    SYSTEM_SHORT_FORM = """You are an expert in creating viral short-form content for TikTok, Instagram Reels, and YouTube Shorts.
Create scripts that:
- Grab attention in the first 1-2 seconds
- Are exactly 30-60 seconds when read at natural pace
- Include hooks, patterns, or trends relevant to the niche
- Have clear visual cues for video creation
- End with engagement or share-worthy moments

Format your response as a JSON object with keys: title, hook, script, description, tags, visual_cues"""

    SYSTEM_TWITTER = """You are an expert Twitter/X content strategist specializing in engaging threads.
Create tweet threads that:
- Start with an attention-grabbing hook
- Build narrative momentum through consecutive tweets
- Use formatting for clarity and visual breaks
- End with a thought-provoking statement or CTA
- Are designed to maximize retweets and engagement

Format your response as a JSON object with keys: tweets (array), theme, engagement_strategy"""

    SYSTEM_TOPIC_IDEAS = """You are a trend analyst specializing in identifying viral content opportunities.
Generate trending, niche-specific topic ideas that:
- Align with current trends and seasonality
- Are underexplored but highly searchable
- Have strong engagement potential
- Appeal to the target audience
- Can be adapted across multiple content formats

Return a JSON object with key 'topics' containing an array of topic ideas with 'title' and 'why_trending' fields."""

    def __init__(
        self,
        api_provider: str = "anthropic",
        api_key: Optional[str] = None,
        output_dir: str = "./outputs/scripts",
    ):
        """
        Initialize the script generator.

        Args:
            api_provider: Either 'anthropic' or 'openai'
            api_key: API key for the provider. If None, uses env vars
            output_dir: Directory to save generated scripts
        """
        self.api_provider = api_provider.lower()
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        if self.api_provider == "anthropic":
            self.client = anthropic.Anthropic(
                api_key=api_key or os.getenv("ANTHROPIC_API_KEY")
            )
            self.model = "claude-sonnet-4-5"
        elif self.api_provider == "openai":
            openai.api_key = api_key or os.getenv("OPENAI_API_KEY")
            self.client = openai.OpenAI(api_key=openai.api_key)
            self.model = "gpt-4o-mini"
        else:
            raise ValueError(f"Unsupported API provider: {api_provider}")

    def _call_llm(self, system_prompt: str, user_message: str) -> str:
        """Call the LLM with the given prompts."""
        try:
            if self.api_provider == "anthropic":
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                )
                return response.content[0].text
            else:  # openai
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=4096,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                )
                return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error calling {self.api_provider} API: {e}")
            raise

    def _extract_json(self, response: str) -> Dict[str, Any]:
        """Extract and parse JSON from LLM response."""
        try:
            # Try to find JSON in the response
            start_idx = response.find("{")
            end_idx = response.rfind("}") + 1
            if start_idx == -1 or end_idx <= start_idx:
                raise ValueError("No JSON found in response")
            json_str = response[start_idx:end_idx]
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from response: {e}")
            raise

    def _save_script(self, content_type: str, data: Dict[str, Any]) -> str:
        """Save generated script to file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{content_type}_{timestamp}.json"
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Script saved to {filepath}")
        return filepath

    def generate_long_form(
        self, topic: str, niche: str, duration_min: int = 10
    ) -> Dict[str, Any]:
        """
        Generate a long-form video script (10+ minutes).

        Args:
            topic: Main topic for the video
            niche: Target niche/audience
            duration_min: Desired duration in minutes

        Returns:
            Dictionary with title, hook, script, description, tags
        """
        user_message = f"""Create a {duration_min}-minute video script about '{topic}' for a {niche} audience.

The script should:
- Be well-researched and authoritative
- Include specific examples and data points
- Have a clear story arc with multiple acts
- Include timestamps for key sections
- Be approximately {duration_min * 150} words

Topic: {topic}
Niche: {niche}"""

        response = self._call_llm(self.SYSTEM_LONG_FORM, user_message)
        data = self._extract_json(response)
        data["generated_at"] = datetime.now().isoformat()
        data["api_provider"] = self.api_provider

        self._save_script("long_form", data)
        return data

    def generate_short_form(self, topic: str, niche: str) -> Dict[str, Any]:
        """
        Generate a short-form video script (30-60 seconds).

        Args:
            topic: Main topic for the video
            niche: Target niche/audience

        Returns:
            Dictionary with title, hook, script, description, tags, visual_cues
        """
        user_message = f"""Create a 30-60 second short-form video script about '{topic}' for a {niche} audience.

The script should:
- Start with a hook in the first 2 seconds
- Be fast-paced and engaging
- Include specific visual cues for editing
- Use trending formats or patterns when appropriate
- Include natural pause points for scene transitions

Topic: {topic}
Niche: {niche}"""

        response = self._call_llm(self.SYSTEM_SHORT_FORM, user_message)
        data = self._extract_json(response)
        data["generated_at"] = datetime.now().isoformat()
        data["api_provider"] = self.api_provider

        self._save_script("short_form", data)
        return data

    def generate_twitter_thread(
        self, topic: str, niche: str, num_tweets: int = 5
    ) -> Dict[str, Any]:
        """
        Generate a Twitter/X thread.

        Args:
            topic: Main topic for the thread
            niche: Target niche/audience
            num_tweets: Number of tweets in the thread

        Returns:
            Dictionary with tweets array and engagement strategy
        """
        user_message = f"""Create a {num_tweets}-tweet thread about '{topic}' for a {niche} audience.

Each tweet should:
- Be exactly under 280 characters
- Build on the previous tweet's idea
- Maintain a consistent theme
- Include relevant hooks and insights
- Include a numbering prefix (1/, 2/, etc.)

Topic: {topic}
Niche: {niche}
Number of tweets: {num_tweets}"""

        response = self._call_llm(self.SYSTEM_TWITTER, user_message)
        data = self._extract_json(response)
        data["generated_at"] = datetime.now().isoformat()
        data["api_provider"] = self.api_provider

        self._save_script("twitter_thread", data)
        return data

    def suggest_topics(self, niche: str, count: int = 10) -> Dict[str, List[str]]:
        """
        Suggest trending topics for a specific niche.

        Args:
            niche: Target niche/audience
            count: Number of topic suggestions

        Returns:
            Dictionary with 'topics' key containing list of topic ideas
        """
        user_message = f"""Generate {count} trending topic ideas for the '{niche}' niche.

Each topic should:
- Be timely and relevant
- Have strong engagement potential
- Be specific and actionable
- Work across multiple content formats

Return topics with brief explanations of why they're trending."""

        response = self._call_llm(self.SYSTEM_TOPIC_IDEAS, user_message)
        data = self._extract_json(response)
        data["generated_at"] = datetime.now().isoformat()
        data["api_provider"] = self.api_provider

        self._save_script("topic_suggestions", data)
        return data


def main():
    """Example usage of ScriptGenerator."""
    generator = ScriptGenerator(api_provider="anthropic")

    # Example: Generate long-form script
    print("Generating long-form script...")
    long_form = generator.generate_long_form(
        topic="AI Tools for Content Creation",
        niche="Digital Content Creators",
        duration_min=10,
    )
    print(f"Generated: {long_form['title']}")

    # Example: Generate short-form script
    print("\nGenerating short-form script...")
    short_form = generator.generate_short_form(
        topic="Quick Python Tips", niche="Software Developers"
    )
    print(f"Generated: {short_form['title']}")

    # Example: Generate Twitter thread
    print("\nGenerating Twitter thread...")
    thread = generator.generate_twitter_thread(
        topic="The Future of AI", niche="Tech Enthusiasts", num_tweets=7
    )
    print(f"Generated {len(thread['tweets'])} tweets")

    # Example: Get topic suggestions
    print("\nSuggesting topics...")
    topics = generator.suggest_topics(niche="Digital Marketing", count=5)
    print(f"Got {len(topics.get('topics', []))} topic suggestions")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
