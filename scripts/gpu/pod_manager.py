"""
RunPod on-demand pod lifecycle manager for the CommonCreed pipeline.

Usage pattern (one pod per daily run):

    async with PodManager(config) as comfyui_url:
        # pod is running, ComfyUI is healthy
        await generate_avatar(comfyui_url, ...)
        await generate_broll(comfyui_url, ...)
    # pod is stopped here (even on exception)

The pod is STOPPED (not terminated) after each run so the volume
(model weights ~50 GB) is preserved for next-day reuse, avoiding
a 10-30 minute re-download on every run.

Required env vars:
    RUNPOD_API_KEY          — RunPod API key
    RUNPOD_GPU_TYPE_ID      — GPU type ID (default: "NVIDIA GeForce RTX 4090")
    RUNPOD_TEMPLATE_ID      — Network volume template ID with ComfyUI pre-installed
                              (optional; falls back to runpod/comfyui:latest image)
    RUNPOD_NETWORK_VOLUME_ID — Network volume ID to attach (optional but recommended)
    RUNPOD_COMFYUI_PORT     — Port ComfyUI listens on (default: 8188)
"""

import asyncio
import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class PodStartupError(RuntimeError):
    pass


class PodManager:
    """
    Async context manager that starts a RunPod on-demand pod, waits for
    ComfyUI to be healthy, yields the ComfyUI URL, then stops the pod.

    Example:
        async with PodManager(config) as comfyui_url:
            client = ComfyUIClient(server_url=comfyui_url)
            ...
    """

    COMFYUI_IMAGE = "runpod/comfyui:latest"
    POD_READY_POLL_INTERVAL_S = 10
    POD_READY_TIMEOUT_S = 300       # 5 min for pod to reach RUNNING
    COMFYUI_READY_TIMEOUT_S = 300   # 5 min for ComfyUI HTTP to respond
    COMFYUI_HEALTH_INTERVAL_S = 10

    def __init__(self, config: dict):
        """
        config keys:
            runpod_api_key          — RunPod API key
            runpod_gpu_type_id      — GPU type string (e.g. "NVIDIA GeForce RTX 4090")
            runpod_template_id      — (optional) pod template ID
            runpod_network_volume_id — (optional) network volume ID
            runpod_comfyui_port     — (optional) defaults to 8188
        """
        import runpod as _runpod

        self._runpod = _runpod
        self._runpod.api_key = config["runpod_api_key"]

        self._gpu_type_id = config.get("runpod_gpu_type_id", "NVIDIA GeForce RTX 4090")
        self._template_id = config.get("runpod_template_id")
        self._network_volume_id = config.get("runpod_network_volume_id")
        self._comfyui_port = int(config.get("runpod_comfyui_port", 8188))

        self._pod_id: Optional[str] = None
        self._comfyui_url: Optional[str] = None

    # ─── Context manager ───────────────────────────────────────────────────

    async def __aenter__(self) -> str:
        """Start the pod and return the ComfyUI base URL."""
        await self._start()
        return self._comfyui_url

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop the pod regardless of success or failure."""
        await self._stop()
        return False  # Do not suppress exceptions

    # ─── Public: manual lifecycle ──────────────────────────────────────────

    async def start(self) -> str:
        """Start the pod and return the ComfyUI base URL. Prefer the context manager."""
        await self._start()
        return self._comfyui_url

    async def stop(self) -> None:
        """Stop the pod. Prefer the context manager."""
        await self._stop()

    # ─── Private ──────────────────────────────────────────────────────────

    async def _start(self) -> None:
        logger.info("Starting RunPod pod (GPU: %s)...", self._gpu_type_id)

        pod = await asyncio.to_thread(self._create_pod)
        self._pod_id = pod["id"]
        logger.info("Pod created: %s", self._pod_id)

        await self._wait_for_running()
        comfyui_url = self._build_comfyui_url()
        await self._wait_for_comfyui(comfyui_url)

        self._comfyui_url = comfyui_url
        logger.info("ComfyUI ready at %s", self._comfyui_url)

    async def _stop(self) -> None:
        if not self._pod_id:
            return
        logger.info("Stopping RunPod pod %s...", self._pod_id)
        try:
            await asyncio.to_thread(self._runpod.stop_pod, self._pod_id)
            logger.info("Pod %s stopped (volume preserved for next run)", self._pod_id)
        except Exception as exc:
            logger.error("Failed to stop pod %s: %s", self._pod_id, exc)
        finally:
            self._pod_id = None
            self._comfyui_url = None

    def _create_pod(self) -> dict:
        """Create a RunPod on-demand pod. Runs in a thread (sync SDK call)."""
        kwargs = dict(
            name=f"commoncreed-{int(time.time())}",
            image_name=self.COMFYUI_IMAGE,
            gpu_type_id=self._gpu_type_id,
            gpu_count=1,
            volume_in_gb=50,
            container_disk_in_gb=20,
            ports=f"{self._comfyui_port}/http",
        )
        if self._template_id:
            kwargs["template_id"] = self._template_id
        if self._network_volume_id:
            kwargs["network_volume_id"] = self._network_volume_id

        pod = self._runpod.create_pod(**kwargs)
        return pod

    async def _wait_for_running(self) -> None:
        """Poll until pod desiredStatus == RUNNING."""
        deadline = time.monotonic() + self.POD_READY_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                info = await asyncio.to_thread(self._runpod.get_pod, self._pod_id)
                status = info.get("desiredStatus") or info.get("status", "")
                logger.debug("Pod %s status: %s", self._pod_id, status)
                if status == "RUNNING":
                    logger.info("Pod %s is RUNNING", self._pod_id)
                    return
            except Exception as exc:
                logger.debug("Pod status check error (will retry): %s", exc)
            await asyncio.sleep(self.POD_READY_POLL_INTERVAL_S)

        raise PodStartupError(
            f"Pod {self._pod_id} did not reach RUNNING within {self.POD_READY_TIMEOUT_S}s"
        )

    def _build_comfyui_url(self) -> str:
        """
        Build the ComfyUI proxy URL for this pod.
        RunPod proxy pattern: https://{pod_id}-{port}.proxy.runpod.net
        """
        return f"https://{self._pod_id}-{self._comfyui_port}.proxy.runpod.net"

    async def _wait_for_comfyui(self, url: str) -> None:
        """Poll GET /system_stats until ComfyUI responds with 200."""
        health_url = f"{url}/system_stats"
        deadline = time.monotonic() + self.COMFYUI_READY_TIMEOUT_S
        logger.info("Waiting for ComfyUI at %s ...", health_url)

        while time.monotonic() < deadline:
            try:
                resp = await asyncio.to_thread(
                    requests.get, health_url, timeout=5
                )
                if resp.status_code == 200:
                    logger.info("ComfyUI is healthy")
                    return
                logger.debug("ComfyUI health check: HTTP %d", resp.status_code)
            except requests.exceptions.RequestException as exc:
                logger.debug("ComfyUI not ready yet: %s", exc)
            await asyncio.sleep(self.COMFYUI_HEALTH_INTERVAL_S)

        raise PodStartupError(
            f"ComfyUI at {url} did not become healthy within {self.COMFYUI_READY_TIMEOUT_S}s"
        )
