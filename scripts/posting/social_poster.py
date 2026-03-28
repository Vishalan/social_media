"""
Cross-platform social media posting with support for YouTube, TikTok, Instagram, and Twitter.

Uses Ayrshare API as primary method with direct API fallbacks.
Includes rate limiting, error handling, and comprehensive logging.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Platform API endpoints
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
TIKTOK_API_BASE = "https://open.tiktokapis.com/v1"
INSTAGRAM_API_BASE = "https://graph.instagram.com/v18.0"
TWITTER_API_BASE = "https://api.twitter.com/2"

# Ayrshare API
AYRSHARE_BASE = "https://api.ayrshare.com/api"


class RateLimiter:
    """Simple rate limiter for API requests."""

    def __init__(self, calls_per_minute: int = 60):
        """Initialize rate limiter."""
        self.calls_per_minute = calls_per_minute
        self.min_interval = 60.0 / calls_per_minute
        self.last_call_time = 0.0

    def wait(self):
        """Wait if necessary to maintain rate limit."""
        import time

        elapsed = time.time() - self.last_call_time
        if elapsed < self.min_interval:
            wait_time = self.min_interval - elapsed
            logger.debug(f"Rate limiting: waiting {wait_time:.2f}s")
            time.sleep(wait_time)
        self.last_call_time = time.time()


class SocialPoster:
    """Post content to multiple social media platforms."""

    def __init__(
        self,
        ayrshare_api_key: Optional[str] = None,
        youtube_credentials: Optional[Dict[str, str]] = None,
        tiktok_token: Optional[str] = None,
        instagram_token: Optional[str] = None,
        twitter_bearer_token: Optional[str] = None,
        log_file: str = "./posts_log.json",
    ):
        """
        Initialize the social poster.

        Args:
            ayrshare_api_key: Ayrshare API key (recommended)
            youtube_credentials: YouTube OAuth credentials dict
            tiktok_token: TikTok API access token
            instagram_token: Instagram Graph API token
            twitter_bearer_token: Twitter API Bearer token
            log_file: Path to JSON log file for tracking posts
        """
        self.ayrshare_key = ayrshare_api_key or os.getenv("AYRSHARE_API_KEY")
        self.youtube_creds = youtube_credentials
        self.tiktok_token = tiktok_token or os.getenv("TIKTOK_API_TOKEN")
        self.instagram_token = instagram_token or os.getenv("INSTAGRAM_API_TOKEN")
        self.twitter_token = twitter_bearer_token or os.getenv("TWITTER_BEARER_TOKEN")

        self.log_file = log_file
        self.rate_limiter = RateLimiter(calls_per_minute=60)

        logger.info("SocialPoster initialized")

    def _log_post(
        self,
        platform: str,
        content_id: str,
        status: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Log a post to the JSON log file."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "content_id": content_id,
            "status": status,
            "metadata": metadata,
        }

        # Read existing log
        logs = []
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file, "r") as f:
                    logs = json.load(f)
            except json.JSONDecodeError:
                logs = []

        # Append and save
        logs.append(log_entry)
        with open(self.log_file, "w") as f:
            json.dump(logs, f, indent=2)

        logger.info(f"Logged post: {platform}/{content_id}")

    def _make_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Make HTTP request with rate limiting and error handling."""
        self.rate_limiter.wait()

        try:
            if method.upper() == "POST":
                response = requests.post(
                    url,
                    headers=headers,
                    json=json_data,
                    files=files,
                    timeout=30,
                )
            elif method.upper() == "GET":
                response = requests.get(url, headers=headers, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()
            return response

        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise

    def post_youtube_video(
        self,
        title: str,
        description: str,
        tags: List[str],
        video_path: str,
        thumbnail_path: Optional[str] = None,
        privacy_status: str = "unlisted",
        affiliate_links: List[str] | None = None,
    ) -> Dict[str, Any]:
        """
        Post a video to YouTube.

        Args:
            title: Video title
            description: Video description
            tags: List of tags/keywords
            video_path: Path to video file
            thumbnail_path: Path to thumbnail image
            privacy_status: 'public', 'unlisted', or 'private'
            affiliate_links: Optional list of affiliate URLs to append to description

        Returns:
            Dictionary with video_id and upload status

        Raises:
            ValueError: If YouTube credentials not configured
            requests.RequestException: If upload fails
        """
        description = self._build_caption_with_affiliates(description, affiliate_links or [])
        description += self._ai_disclosure("youtube")

        if not self.youtube_creds:
            raise ValueError("YouTube credentials not configured")

        logger.info(f"Uploading to YouTube: {title}")

        # For this example, we'll use Ayrshare as a fallback
        if self.ayrshare_key:
            return self._post_youtube_ayrshare(
                title, description, tags, video_path, thumbnail_path, privacy_status
            )

        # Direct YouTube API implementation would go here
        raise NotImplementedError("Direct YouTube API not yet implemented")

    def _post_youtube_ayrshare(
        self,
        title: str,
        description: str,
        tags: List[str],
        video_path: str,
        thumbnail_path: Optional[str],
        privacy_status: str,
    ) -> Dict[str, Any]:
        """Post to YouTube using Ayrshare API."""
        with open(video_path, "rb") as f:
            files = {"media": f}

            data = {
                "service": "youtube",
                "title": title,
                "description": description,
                "tags": ",".join(tags),
            }

            headers = {"Authorization": f"Bearer {self.ayrshare_key}"}

            response = self._make_request(
                "POST", f"{AYRSHARE_BASE}/post", headers=headers, files=files
            )

            result = response.json()

            self._log_post(
                "youtube",
                result.get("id", "unknown"),
                "uploaded",
                {"title": title, "description": description},
            )

            return result

    def post_tiktok(
        self, caption: str, video_path: str, affiliate_links: List[str] | None = None
    ) -> Dict[str, Any]:
        """
        Post a video to TikTok.

        Args:
            caption: Video caption/description
            video_path: Path to video file
            affiliate_links: Optional list of affiliate URLs to append to caption

        Returns:
            Dictionary with video_id and status

        Raises:
            ValueError: If TikTok token not configured
        """
        caption = self._build_caption_with_affiliates(caption, affiliate_links or [])
        caption += self._ai_disclosure("tiktok")

        if not self.tiktok_token:
            if self.ayrshare_key:
                return self._post_tiktok_ayrshare(caption, video_path)
            raise ValueError("TikTok token not configured")

        logger.info("Posting to TikTok")

        # Direct TikTok API implementation
        with open(video_path, "rb") as f:
            url = f"{TIKTOK_API_BASE}/post/publish/"
            headers = {
                "Authorization": f"Bearer {self.tiktok_token}",
                "Content-Type": "application/octet-stream",
            }

            data = {"caption": caption}

            response = self._make_request(
                "POST", url, headers=headers, json_data=data
            )

            result = response.json()

            self._log_post("tiktok", result.get("video_id", "unknown"), "posted", data)

            return result

    def _post_tiktok_ayrshare(self, caption: str, video_path: str) -> Dict[str, Any]:
        """Post to TikTok using Ayrshare API."""
        with open(video_path, "rb") as f:
            files = {"media": f}

            data = {"service": "tiktok", "caption": caption}

            headers = {"Authorization": f"Bearer {self.ayrshare_key}"}

            response = self._make_request(
                "POST", f"{AYRSHARE_BASE}/post", headers=headers, files=files
            )

            result = response.json()

            self._log_post("tiktok", result.get("id", "unknown"), "posted", data)

            return result

    def post_instagram_reel(
        self, caption: str, video_path: str, affiliate_links: List[str] | None = None
    ) -> Dict[str, Any]:
        """
        Post a reel to Instagram.

        Args:
            caption: Reel caption
            video_path: Path to video file
            affiliate_links: Optional list of affiliate URLs to append to caption

        Returns:
            Dictionary with media_id and status
        """
        caption = self._build_caption_with_affiliates(caption, affiliate_links or [])
        caption += self._ai_disclosure("instagram")

        if not self.instagram_token:
            if self.ayrshare_key:
                return self._post_instagram_ayrshare(caption, video_path)
            raise ValueError("Instagram token not configured")

        logger.info("Posting to Instagram")

        # Would use Instagram Graph API
        raise NotImplementedError("Direct Instagram API not yet implemented")

    def _post_instagram_ayrshare(self, caption: str, video_path: str) -> Dict[str, Any]:
        """Post to Instagram using Ayrshare API."""
        with open(video_path, "rb") as f:
            files = {"media": f}

            data = {"service": "instagram", "caption": caption}

            headers = {"Authorization": f"Bearer {self.ayrshare_key}"}

            response = self._make_request(
                "POST", f"{AYRSHARE_BASE}/post", headers=headers, files=files
            )

            result = response.json()

            self._log_post("instagram", result.get("id", "unknown"), "posted", data)

            return result

    def upload_media(self, file_path: str) -> str:
        """
        Upload a local audio or video file to Ayrshare media hosting.

        Returns a publicly accessible URL (expires after ~24h).
        Used to host ElevenLabs audio before passing URL to HeyGen/Kling avatar API.

        Args:
            file_path: Path to the local audio or video file to upload.

        Returns:
            Publicly accessible URL string for the uploaded file.

        Raises:
            ValueError: If Ayrshare API key is not configured.
            RuntimeError: If the upload request fails.
        """
        if not self.ayrshare_key:
            raise ValueError("Ayrshare API key required for media upload")

        logger.info(f"Uploading media to Ayrshare: {file_path}")

        headers = {"Authorization": f"Bearer {self.ayrshare_key}"}

        with open(file_path, "rb") as f:
            files = {"file": f}

            try:
                resp = self._make_request(
                    "POST",
                    f"{AYRSHARE_BASE}/media/upload",
                    headers=headers,
                    files=files,
                )
            except requests.HTTPError as e:
                resp = e.response
                raise RuntimeError(
                    f"Media upload failed ({resp.status_code}): {resp.text}"
                ) from e

        return resp.json()["url"]

    def post_twitter(
        self, text: str, media_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Post a tweet.

        Args:
            text: Tweet text
            media_path: Optional path to image/video file

        Returns:
            Dictionary with tweet_id and status
        """
        if not self.twitter_token:
            raise ValueError("Twitter bearer token not configured")

        logger.info(f"Posting to Twitter: {text[:50]}...")

        headers = {
            "Authorization": f"Bearer {self.twitter_token}",
            "Content-Type": "application/json",
        }

        payload = {"text": text}

        response = self._make_request(
            "POST",
            f"{TWITTER_API_BASE}/tweets",
            headers=headers,
            json_data=payload,
        )

        result = response.json()

        tweet_id = result.get("data", {}).get("id")

        self._log_post("twitter", tweet_id, "posted", {"text": text})

        return result

    def post_all_short_form(
        self,
        caption: str,
        video_path: str,
        hashtags: List[str],
        affiliate_links: List[str] | None = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Post the same video to all short-form platforms.

        Args:
            caption: Video caption
            video_path: Path to video file
            hashtags: List of hashtags to include
            affiliate_links: Optional list of affiliate URLs to append to captions

        Returns:
            Dictionary with results for each platform
        """
        caption_with_tags = f"{caption} {' '.join(hashtags)}"
        results = {}

        platforms = ["tiktok", "instagram", "twitter"]

        for platform in platforms:
            try:
                logger.info(f"Posting to {platform}...")

                if platform == "tiktok":
                    results[platform] = self.post_tiktok(
                        caption_with_tags, video_path, affiliate_links
                    )
                elif platform == "instagram":
                    results[platform] = self.post_instagram_reel(
                        caption_with_tags, video_path, affiliate_links
                    )
                elif platform == "twitter":
                    results[platform] = self.post_twitter(caption_with_tags, video_path)

            except Exception as e:
                logger.error(f"Failed to post to {platform}: {e}")
                results[platform] = {"error": str(e), "status": "failed"}

        return results

    _DISCLOSURES = {
        "instagram": "\n\n[AI-generated content]",
        "tiktok": "\n\n#AIGenerated #SyntheticMedia",
        "youtube": "\n\nThis video contains AI-generated/altered content.",
    }

    def _build_caption_with_affiliates(
        self, caption: str, affiliate_links: list[str]
    ) -> str:
        """Append affiliate links to caption, one per line."""
        if not affiliate_links:
            return caption
        links_block = "\n".join(affiliate_links)
        return f"{caption}\n\n{links_block}"

    def _ai_disclosure(self, platform: str) -> str:
        """Return platform-specific AI disclosure text."""
        return self._DISCLOSURES.get(platform, "")

    def schedule_post(
        self,
        platform: str,
        content: Dict[str, Any],
        scheduled_time: str,
    ) -> Dict[str, Any]:
        """
        Schedule a post for future publishing.

        Args:
            platform: Social platform (youtube, tiktok, instagram, twitter)
            content: Content dictionary with title, description, video_path, etc.
            scheduled_time: ISO 8601 formatted datetime string

        Returns:
            Dictionary with schedule_id and status

        Raises:
            ValueError: If platform not supported
        """
        if platform not in ["youtube", "tiktok", "instagram", "twitter"]:
            raise ValueError(f"Unsupported platform: {platform}")

        logger.info(f"Scheduling post to {platform} for {scheduled_time}")

        if not self.ayrshare_key:
            raise ValueError("Ayrshare API key required for scheduling")

        data = {
            "service": platform,
            "post": content,
            "scheduledTime": scheduled_time,
        }

        headers = {"Authorization": f"Bearer {self.ayrshare_key}"}

        response = self._make_request(
            "POST",
            f"{AYRSHARE_BASE}/schedule",
            headers=headers,
            json_data=data,
        )

        result = response.json()

        self._log_post(
            f"{platform}_scheduled",
            result.get("id", "unknown"),
            "scheduled",
            {"scheduled_time": scheduled_time},
        )

        return result


def main():
    """Example usage of SocialPoster."""
    poster = SocialPoster(ayrshare_api_key="your_key_here")

    # Example: Schedule multiple posts
    content = {
        "title": "AI Tools for 2024",
        "description": "Exploring the latest AI tools for content creators",
        "video_path": "./sample_video.mp4",
    }

    scheduled_time = "2024-04-01T10:00:00Z"

    for platform in ["youtube", "tiktok", "instagram"]:
        try:
            result = poster.schedule_post(platform, content, scheduled_time)
            print(f"Scheduled to {platform}: {result}")
        except Exception as e:
            print(f"Error scheduling to {platform}: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
