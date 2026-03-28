#!/usr/bin/env python3
"""
One-time HeyGen Instant Avatar setup tool.
Run this once to train your custom avatar, then add HEYGEN_AVATAR_ID to .env.

Usage:
    python setup_heygen_avatar.py --video /path/to/reference.mp4 --name "My Avatar"

The --api-key defaults to HEYGEN_API_KEY env var.
"""

import sys
import time
from pathlib import Path

import click
import requests

_HEYGEN_BASE = "https://api.heygen.com"
_ASSET_URL = f"{_HEYGEN_BASE}/v1/asset"
_GROUP_CREATE_URL = f"{_HEYGEN_BASE}/v2/photo_avatar/avatar_group/create"
_TRAIN_URL = f"{_HEYGEN_BASE}/v2/photo_avatar/train"
_TRAIN_STATUS_URL = f"{_HEYGEN_BASE}/v2/photo_avatar/train/status"
_AVATARS_URL = f"{_HEYGEN_BASE}/v2/avatars"

_POLL_INTERVAL_S = 15
_TIMEOUT_S = 60 * 60  # 60 minutes


def _headers(api_key: str) -> dict:
    return {
        "X-Api-Key": api_key,
        "Accept": "application/json",
    }


def _json_headers(api_key: str) -> dict:
    return {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _upload_video(video_path: str, api_key: str) -> str:
    """
    Upload the reference video as a HeyGen asset.

    Returns:
        asset_key string on success.
    """
    click.echo(f"[1/5] Uploading reference video: {video_path}")
    video_file = Path(video_path)
    with open(video_file, "rb") as fh:
        resp = requests.post(
            _ASSET_URL,
            headers=_headers(api_key),
            files={"file": (video_file.name, fh, "video/mp4")},
            timeout=120,
        )

    if resp.status_code not in (200, 201):
        click.echo(f"  Upload failed (HTTP {resp.status_code}):", err=True)
        click.echo(f"  {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    asset_key = data.get("data", {}).get("asset_key") or data.get("asset_key")
    if not asset_key:
        click.echo(f"  Upload response missing asset_key: {data}", err=True)
        sys.exit(1)

    click.echo(f"  Asset uploaded. asset_key={asset_key}")
    return asset_key


def _create_avatar_group(name: str, asset_key: str, api_key: str) -> str:
    """
    Submit avatar group creation request.

    Returns:
        group_id string on success.
    """
    click.echo("[2/5] Creating avatar group...")
    resp = requests.post(
        _GROUP_CREATE_URL,
        headers=_json_headers(api_key),
        json={"name": name, "image_key": asset_key},
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        click.echo(f"  Avatar group creation failed (HTTP {resp.status_code}):", err=True)
        click.echo(f"  {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    group_id = data.get("data", {}).get("group_id") or data.get("group_id")
    if not group_id:
        click.echo(f"  Response missing group_id: {data}", err=True)
        sys.exit(1)

    click.echo(f"  Avatar group created. group_id={group_id}")
    return group_id


def _trigger_training(group_id: str, api_key: str) -> None:
    """Trigger training for the avatar group."""
    click.echo("[3/5] Triggering avatar training...")
    resp = requests.post(
        _TRAIN_URL,
        headers=_json_headers(api_key),
        json={"group_id": group_id},
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        click.echo(f"  Training trigger failed (HTTP {resp.status_code}):", err=True)
        click.echo(f"  {resp.text}", err=True)
        sys.exit(1)

    click.echo("  Training started.")


def _poll_training_status(group_id: str, api_key: str) -> None:
    """
    Poll training status until completed or failed.
    Times out after 60 minutes.
    """
    click.echo("[4/5] Waiting for training to complete (this can take up to 60 minutes)...")
    click.echo("  Progress: ", nl=False)

    deadline = time.monotonic() + _TIMEOUT_S
    while time.monotonic() < deadline:
        resp = requests.get(
            f"{_TRAIN_STATUS_URL}/{group_id}",
            headers=_headers(api_key),
            timeout=30,
        )

        if resp.status_code != 200:
            click.echo()
            click.echo(f"  Status check failed (HTTP {resp.status_code}):", err=True)
            click.echo(f"  {resp.text}", err=True)
            sys.exit(1)

        data = resp.json()
        status = (
            data.get("data", {}).get("status")
            or data.get("status", "")
        )

        if status == "completed":
            click.echo(" done!")
            return

        if status == "failed":
            click.echo()
            error_msg = (
                data.get("data", {}).get("error")
                or data.get("error", "unknown error")
            )
            click.echo(f"  Training failed: {error_msg}", err=True)
            sys.exit(1)

        # pending or processing — print a dot and wait
        click.echo(".", nl=False)
        time.sleep(_POLL_INTERVAL_S)

    click.echo()
    click.echo(
        f"  Training timed out after {_TIMEOUT_S // 60} minutes. "
        "The avatar may still be training in HeyGen — check your dashboard.",
        err=True,
    )
    sys.exit(1)


def _get_avatar_id(group_id: str, name: str, api_key: str) -> tuple[str, str]:
    """
    List avatars and find the one matching group_id or name.

    Returns:
        (avatar_id, avatar_name) tuple.
    """
    click.echo("[5/5] Retrieving avatar ID...")
    resp = requests.get(
        _AVATARS_URL,
        headers=_headers(api_key),
        timeout=30,
    )

    if resp.status_code != 200:
        click.echo(f"  Failed to list avatars (HTTP {resp.status_code}):", err=True)
        click.echo(f"  {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    avatars = data.get("data", {}).get("avatars") or data.get("avatars", [])

    # Try to match by group_id first, then by name
    for avatar in avatars:
        if avatar.get("group_id") == group_id:
            return avatar["avatar_id"], avatar.get("avatar_name", name)

    for avatar in avatars:
        if avatar.get("avatar_name", "").lower() == name.lower():
            return avatar["avatar_id"], avatar.get("avatar_name", name)

    # If no exact match, inform the user and print all available avatars
    click.echo("  Could not automatically match the new avatar. Available avatars:", err=True)
    for avatar in avatars:
        click.echo(
            f"    ID={avatar.get('avatar_id')}  Name={avatar.get('avatar_name')}  "
            f"GroupID={avatar.get('group_id', 'n/a')}",
            err=True,
        )
    click.echo("  Set HEYGEN_AVATAR_ID manually from the list above.", err=True)
    sys.exit(1)


@click.command()
@click.option(
    "--video",
    required=True,
    type=click.Path(exists=True),
    help="Path to reference video (MP4, 10-30s, 1080p recommended)",
)
@click.option(
    "--name",
    default="CommonCreed Avatar",
    show_default=True,
    help="Display name for the avatar",
)
@click.option(
    "--api-key",
    envvar="HEYGEN_API_KEY",
    required=True,
    help="HeyGen API key (defaults to HEYGEN_API_KEY env var)",
)
def setup(video: str, name: str, api_key: str) -> None:
    """Train a custom HeyGen Instant Avatar from a reference video.

    Run this once. When complete, copy the printed HEYGEN_AVATAR_ID into
    your .env file.
    """
    click.echo(f"\nHeyGen Instant Avatar Setup")
    click.echo(f"  Video : {video}")
    click.echo(f"  Name  : {name}")
    click.echo()

    asset_key = _upload_video(video, api_key)
    group_id = _create_avatar_group(name, asset_key, api_key)
    _trigger_training(group_id, api_key)
    _poll_training_status(group_id, api_key)
    avatar_id, avatar_name = _get_avatar_id(group_id, name, api_key)

    click.echo()
    click.echo("✓ Avatar training complete!")
    click.echo()
    click.echo("Add this to your .env file:")
    click.echo(f"  HEYGEN_AVATAR_ID={avatar_id}")
    click.echo()
    click.echo("Avatar details:")
    click.echo(f"  Name     : {avatar_name}")
    click.echo(f"  ID       : {avatar_id}")
    click.echo(f"  Group ID : {group_id}")
    click.echo()


if __name__ == "__main__":
    setup()
