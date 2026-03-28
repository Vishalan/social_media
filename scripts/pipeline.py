"""
Master orchestrator for the complete social media content pipeline.

Coordinates script generation, voice-over, video generation, posting, and analytics.
Provides CLI interface for easy automation and scheduling.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

# Import pipeline modules
from content_gen.script_generator import ScriptGenerator
from voiceover.voice_generator import VoiceGenerator
from video_gen.comfyui_client import ComfyUIClient
from posting.social_poster import SocialPoster
from analytics.tracker import AnalyticsTracker

logger = logging.getLogger(__name__)
console = Console()


class ContentPipeline:
    """Orchestrate the complete content creation pipeline."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        api_provider: str = "anthropic",
        comfyui_url: str = "http://localhost:8188",
        output_base_dir: str = "./outputs",
    ):
        """
        Initialize the content pipeline.

        Args:
            config_path: Path to configuration file
            api_provider: 'anthropic' or 'openai'
            comfyui_url: ComfyUI server URL
            output_base_dir: Base directory for all outputs
        """
        self.config = self._load_config(config_path) if config_path else {}
        self.api_provider = api_provider
        self.comfyui_url = comfyui_url
        self.output_base_dir = output_base_dir

        # Initialize pipeline components
        self.script_gen = ScriptGenerator(
            api_provider=api_provider,
            output_dir=os.path.join(output_base_dir, "scripts"),
        )

        self.voice_gen = VoiceGenerator()

        self.comfyui = ComfyUIClient(server_url=comfyui_url)

        self.poster = SocialPoster(
            ayrshare_api_key=os.getenv("AYRSHARE_API_KEY"),
            youtube_credentials=self.config.get("youtube"),
            tiktok_token=os.getenv("TIKTOK_API_TOKEN"),
            instagram_token=os.getenv("INSTAGRAM_API_TOKEN"),
            twitter_bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
            log_file=os.path.join(output_base_dir, "posts_log.json"),
        )

        self.tracker = AnalyticsTracker(
            db_path=os.path.join(output_base_dir, "analytics.db")
        )

        logger.info("ContentPipeline initialized")

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    def _create_output_dirs(self) -> None:
        """Create necessary output directories."""
        dirs = [
            os.path.join(self.output_base_dir, "scripts"),
            os.path.join(self.output_base_dir, "voiceovers"),
            os.path.join(self.output_base_dir, "videos"),
            os.path.join(self.output_base_dir, "thumbnails"),
            os.path.join(self.output_base_dir, "logs"),
        ]

        for dir_path in dirs:
            os.makedirs(dir_path, exist_ok=True)

    async def generate_single_video(
        self,
        topic: str,
        niche: str,
        video_type: str = "short_form",
        voice_name: str = "Rachel",
        generate_voiceover: bool = True,
        generate_video: bool = True,
        post_to_platforms: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate a complete video from topic to posting.

        Args:
            topic: Content topic
            niche: Target niche
            video_type: 'long_form', 'short_form'
            voice_name: Voice for voiceover
            generate_voiceover: Whether to generate voiceover
            generate_video: Whether to generate video
            post_to_platforms: List of platforms to post to

        Returns:
            Dictionary with all generated assets and status
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result = {
            "topic": topic,
            "niche": niche,
            "video_type": video_type,
            "timestamp": timestamp,
            "status": "in_progress",
            "assets": {},
        }

        console.print(f"\n[bold cyan]Generating {video_type} video[/bold cyan]")
        console.print(f"Topic: {topic}")
        console.print(f"Niche: {niche}\n")

        # Step 1: Generate script
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("[cyan]Generating script...", total=None)

            if video_type == "long_form":
                script_data = self.script_gen.generate_long_form(topic, niche)
            else:
                script_data = self.script_gen.generate_short_form(topic, niche)

        result["assets"]["script"] = script_data
        console.print(f"✓ Script generated: {script_data['title']}\n")

        # Step 2: Generate voiceover
        if generate_voiceover:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("[cyan]Generating voiceover...", total=None)

                vo_output = os.path.join(
                    self.output_base_dir,
                    "voiceovers",
                    f"vo_{timestamp}.mp3",
                )

                try:
                    vo_path = self.voice_gen.generate(
                        script_data["script"],
                        vo_output,
                        voice_name=voice_name,
                    )
                    result["assets"]["voiceover"] = vo_path
                    console.print(f"✓ Voiceover generated: {vo_path}\n")

                except Exception as e:
                    logger.error(f"Voiceover generation failed: {e}")
                    console.print(f"✗ Voiceover generation failed: {e}\n", style="red")

        # Step 3: Generate video
        if generate_video:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("[cyan]Generating video...", total=None)

                video_output = os.path.join(
                    self.output_base_dir,
                    "videos",
                    f"video_{timestamp}.mp4",
                )

                try:
                    video_path = await self.comfyui.generate_short_video(
                        script_data["title"],
                        video_output,
                    )
                    result["assets"]["video"] = video_path
                    console.print(f"✓ Video generated: {video_path}\n")

                except Exception as e:
                    logger.error(f"Video generation failed: {e}")
                    console.print(f"✗ Video generation failed: {e}\n", style="red")

        # Step 4: Post to social platforms
        if post_to_platforms and "video" in result["assets"]:
            console.print("[cyan]Posting to social platforms...[/cyan]")

            caption = script_data.get("description", script_data.get("title"))
            hashtags = script_data.get("tags", [])

            if hashtags:
                caption += " " + " ".join([f"#{tag}" for tag in hashtags[:5]])

            try:
                post_results = self.poster.post_all_short_form(
                    caption,
                    result["assets"]["video"],
                    hashtags,
                )
                result["assets"]["posts"] = post_results

                for platform, post_result in post_results.items():
                    if "error" not in post_result:
                        console.print(f"✓ Posted to {platform}", style="green")
                    else:
                        console.print(f"✗ Failed to post to {platform}", style="red")

            except Exception as e:
                logger.error(f"Posting failed: {e}")
                console.print(f"✗ Posting failed: {e}\n", style="red")

        # Step 5: Log to analytics
        post_id = f"auto_{timestamp}"
        self.tracker.log_post(
            platform="multi",
            content_id=post_id,
            metadata={
                "title": script_data.get("title"),
                "description": script_data.get("description"),
            },
        )

        result["status"] = "completed"
        console.print("\n[bold green]✓ Pipeline completed successfully[/bold green]\n")

        return result

    async def run_daily(self) -> None:
        """Run complete daily content generation pipeline."""
        console.print(
            "[bold magenta]Daily Content Generation Pipeline[/bold magenta]\n"
        )

        # Load daily config or use defaults
        daily_config = self.config.get("daily", {})
        niches = daily_config.get("niches", ["Technology"])
        topics_per_niche = daily_config.get("topics_per_niche", 1)

        results = []

        for niche in niches:
            console.print(f"\n[bold cyan]Processing niche: {niche}[/bold cyan]")

            # Get topic suggestions
            topics = self.script_gen.suggest_topics(niche, count=topics_per_niche)

            for topic_info in topics.get("topics", [])[:topics_per_niche]:
                topic = (
                    topic_info["title"]
                    if isinstance(topic_info, dict)
                    else topic_info
                )

                try:
                    result = await self.generate_single_video(
                        topic=topic,
                        niche=niche,
                        video_type="short_form",
                        post_to_platforms=daily_config.get(
                            "post_platforms", ["tiktok", "twitter"]
                        ),
                    )
                    results.append(result)

                except Exception as e:
                    logger.error(f"Failed to generate content for {topic}: {e}")
                    console.print(f"✗ Failed: {e}\n", style="red")

        # Generate summary report
        console.print("\n[bold cyan]Daily Summary[/bold cyan]")
        summary_table = Table(title="Daily Pipeline Summary")
        summary_table.add_column("Topic", style="cyan")
        summary_table.add_column("Status", style="magenta")

        for result in results:
            summary_table.add_row(result["topic"], result["status"])

        console.print(summary_table)

    async def run_weekly_batch(self, videos_per_day: int = 2) -> None:
        """Run weekly batch content generation."""
        console.print(
            "[bold magenta]Weekly Batch Content Generation[/bold magenta]\n"
        )

        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        total_videos = len(days) * videos_per_day

        with Progress(console=console) as progress:
            task = progress.add_task(
                "[cyan]Generating videos...", total=total_videos
            )

            for day_idx, day in enumerate(days):
                console.print(f"\n[bold]{day}[/bold]")

                for video_num in range(videos_per_day):
                    try:
                        result = await self.generate_single_video(
                            topic=f"Content for {day} - Video {video_num + 1}",
                            niche="Technology",
                            video_type="short_form",
                        )
                        progress.update(task, advance=1)

                    except Exception as e:
                        logger.error(f"Failed to generate video: {e}")
                        progress.update(task, advance=1)

        console.print(f"\n[bold green]✓ Weekly batch completed[/bold green]")

    def generate_report(self, period: str = "week") -> Dict[str, Any]:
        """Generate performance report."""
        return self.tracker.get_report(period)

    def close(self) -> None:
        """Clean up resources."""
        self.tracker.close()
        logger.info("Pipeline closed")


@click.group()
def cli():
    """Social Media Content Pipeline CLI."""
    pass


@cli.command()
@click.option(
    "--api-provider",
    default="anthropic",
    type=click.Choice(["anthropic", "openai"]),
    help="LLM API provider",
)
@click.option(
    "--comfyui-url",
    default="http://localhost:8188",
    help="ComfyUI server URL",
)
@click.option(
    "--output-dir",
    default="./outputs",
    help="Output directory",
)
def daily(api_provider: str, comfyui_url: str, output_dir: str):
    """Run daily content generation pipeline."""
    logging.basicConfig(level=logging.INFO)

    pipeline = ContentPipeline(
        api_provider=api_provider,
        comfyui_url=comfyui_url,
        output_base_dir=output_dir,
    )

    try:
        asyncio.run(pipeline.run_daily())
    finally:
        pipeline.close()


@cli.command()
@click.option("--topic", prompt="Content topic", help="Topic for the video")
@click.option(
    "--niche",
    prompt="Target niche",
    default="Technology",
    help="Target audience niche",
)
@click.option(
    "--type",
    "video_type",
    default="short_form",
    type=click.Choice(["long_form", "short_form"]),
    help="Video type",
)
@click.option(
    "--voice",
    default="Rachel",
    help="Voice for voiceover",
)
@click.option(
    "--no-voiceover",
    is_flag=True,
    help="Skip voiceover generation",
)
@click.option(
    "--no-video",
    is_flag=True,
    help="Skip video generation",
)
@click.option(
    "--post",
    multiple=True,
    help="Platform to post to (tiktok, twitter, instagram, youtube)",
)
@click.option(
    "--api-provider",
    default="anthropic",
    type=click.Choice(["anthropic", "openai"]),
    help="LLM API provider",
)
@click.option(
    "--output-dir",
    default="./outputs",
    help="Output directory",
)
def single(
    topic: str,
    niche: str,
    video_type: str,
    voice: str,
    no_voiceover: bool,
    no_video: bool,
    post: tuple,
    api_provider: str,
    output_dir: str,
):
    """Generate a single video from topic to posting."""
    logging.basicConfig(level=logging.INFO)

    pipeline = ContentPipeline(
        api_provider=api_provider,
        output_base_dir=output_dir,
    )

    try:
        result = asyncio.run(
            pipeline.generate_single_video(
                topic=topic,
                niche=niche,
                video_type=video_type,
                voice_name=voice,
                generate_voiceover=not no_voiceover,
                generate_video=not no_video,
                post_to_platforms=list(post) if post else None,
            )
        )

        # Display result
        console.print("\n[bold green]Generation Complete[/bold green]\n")
        console.print(f"Title: {result['assets'].get('script', {}).get('title')}")
        console.print(f"Status: {result['status']}")

    finally:
        pipeline.close()


@cli.command()
@click.option(
    "--period",
    default="week",
    type=click.Choice(["day", "week", "month", "all"]),
    help="Report period",
)
@click.option(
    "--output-dir",
    default="./outputs",
    help="Output directory",
)
def report(period: str, output_dir: str):
    """Generate analytics report."""
    logging.basicConfig(level=logging.INFO)

    pipeline = ContentPipeline(output_base_dir=output_dir)

    try:
        report_data = pipeline.generate_report(period)

        # Display report
        console.print(f"\n[bold cyan]{period.upper()} Report[/bold cyan]\n")
        console.print(json.dumps(report_data, indent=2))

    finally:
        pipeline.close()


@cli.command()
@click.option(
    "--api-provider",
    default="anthropic",
    type=click.Choice(["anthropic", "openai"]),
    help="LLM API provider",
)
@click.option(
    "--output-dir",
    default="./outputs",
    help="Output directory",
)
def weekly(api_provider: str, output_dir: str):
    """Run weekly batch content generation."""
    logging.basicConfig(level=logging.INFO)

    pipeline = ContentPipeline(
        api_provider=api_provider,
        output_base_dir=output_dir,
    )

    try:
        asyncio.run(pipeline.run_weekly_batch(videos_per_day=2))
    finally:
        pipeline.close()


def main():
    """Main entry point."""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[red]Pipeline interrupted by user[/red]")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        console.print(f"\n[red]Error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
