"""
ComfyUI API client for video and image generation.

Supports both local ComfyUI instances and cloud-hosted ComfyUI services.
Provides high-level convenience methods for common generation tasks.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import aiohttp
import requests
import websockets

logger = logging.getLogger(__name__)


class ComfyUIClient:
    """Client for ComfyUI API."""

    def __init__(
        self,
        server_url: str = "http://localhost:8188",
        api_key: Optional[str] = None,
        timeout: int = 300,
    ):
        """
        Initialize ComfyUI client.

        Args:
            server_url: ComfyUI server URL (local or cloud)
            api_key: API key if using cloud service (optional)
            timeout: Timeout for long-running operations in seconds
        """
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = None
        self._prompt_id_counter = 0

        logger.info(f"ComfyUIClient initialized for {self.server_url}")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session

    async def close(self):
        """Close the aiohttp session."""
        if self.session:
            await self.session.close()
            self.session = None

    def _prepare_headers(self) -> Dict[str, str]:
        """Prepare HTTP headers."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _substitute_params(
        self, workflow_json: Dict[str, Any], params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Substitute parameters in workflow JSON.

        Supports {{param_name}} placeholders in string values.

        Args:
            workflow_json: Workflow JSON with placeholders
            params: Parameter values to substitute

        Returns:
            Workflow JSON with substituted parameters
        """
        import copy

        workflow = copy.deepcopy(workflow_json)

        def substitute_value(obj: Any) -> Any:
            if isinstance(obj, str):
                for key, value in params.items():
                    obj = obj.replace(f"{{{{{key}}}}}", str(value))
                return obj
            elif isinstance(obj, dict):
                return {k: substitute_value(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [substitute_value(item) for item in obj]
            return obj

        return substitute_value(workflow)

    async def run_workflow(
        self,
        workflow_json: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None,
        wait_for_completion: bool = True,
    ) -> str:
        """
        Submit and execute a workflow.

        Args:
            workflow_json: ComfyUI workflow JSON
            params: Parameters to substitute in workflow
            wait_for_completion: Whether to wait for completion

        Returns:
            Prompt ID for tracking the execution

        Raises:
            requests.RequestException: If API call fails
        """
        # Prepare workflow with parameter substitution
        workflow = workflow_json
        if params:
            workflow = self._substitute_params(workflow, params)

        try:
            # Submit workflow
            response = requests.post(
                f"{self.server_url}/prompt",
                json={"prompt": workflow},
                headers=self._prepare_headers(),
                timeout=10,
            )
            response.raise_for_status()

            data = response.json()
            prompt_id = data.get("prompt_id")

            if not prompt_id:
                raise ValueError("No prompt_id in response")

            logger.info(f"Workflow submitted with prompt_id: {prompt_id}")

            if wait_for_completion:
                await self._wait_for_completion(prompt_id)

            return prompt_id

        except requests.RequestException as e:
            logger.error(f"Failed to submit workflow: {e}")
            raise

    async def _wait_for_completion(
        self,
        prompt_id: str,
        check_interval: int = 2,
    ) -> None:
        """
        Wait for a workflow to complete via WebSocket.

        Args:
            prompt_id: The prompt ID to monitor
            check_interval: Seconds between status checks
        """
        ws_url = self.server_url.replace("http", "ws") + "/ws"

        try:
            async with websockets.connect(ws_url, ping_interval=None) as websocket:
                logger.info(f"Connected to WebSocket: {ws_url}")

                while True:
                    try:
                        message = await asyncio.wait_for(
                            websocket.recv(), timeout=self.timeout
                        )
                        data = json.loads(message)

                        if data.get("type") == "execution_progress":
                            progress = data.get("data", {})
                            logger.info(
                                f"Progress: {progress.get('node')} "
                                f"({progress.get('value', 0)}/{progress.get('max', 0)})"
                            )

                        elif data.get("type") == "execution_complete":
                            logger.info("Workflow execution completed")
                            return

                        elif data.get("type") == "execution_error":
                            error = data.get("data", {})
                            logger.error(f"Execution error: {error}")
                            raise RuntimeError(f"Workflow error: {error}")

                    except asyncio.TimeoutError:
                        logger.warning("WebSocket timeout, checking status...")
                        status = await self.get_status(prompt_id)
                        if status.get("status") == "completed":
                            return

        except Exception as e:
            logger.warning(f"WebSocket monitoring failed: {e}. Using polling fallback.")
            await self._wait_for_completion_polling(prompt_id, check_interval)

    async def _wait_for_completion_polling(
        self,
        prompt_id: str,
        check_interval: int = 2,
    ) -> None:
        """
        Wait for completion using polling (fallback method).

        Args:
            prompt_id: The prompt ID to monitor
            check_interval: Seconds between status checks
        """
        start_time = time.time()

        while time.time() - start_time < self.timeout:
            status = await self.get_status(prompt_id)

            if status.get("status") == "completed":
                logger.info("Workflow execution completed")
                return

            if status.get("status") == "error":
                logger.error(f"Workflow error: {status.get('error')}")
                raise RuntimeError(f"Workflow error: {status.get('error')}")

            logger.info(f"Status: {status.get('status', 'unknown')}")
            await asyncio.sleep(check_interval)

        raise TimeoutError(f"Workflow did not complete within {self.timeout} seconds")

    async def get_status(self, prompt_id: str) -> Dict[str, Any]:
        """
        Get the status of a workflow execution.

        Args:
            prompt_id: The prompt ID to check

        Returns:
            Status dictionary with status, progress, and output info
        """
        try:
            response = requests.get(
                f"{self.server_url}/prompt/{prompt_id}",
                headers=self._prepare_headers(),
                timeout=10,
            )

            if response.status_code == 404:
                return {"status": "not_found"}

            response.raise_for_status()
            data = response.json()

            # Parse status from response
            if data.get("prompt_id") is None:
                return {"status": "completed", "outputs": data}

            return {
                "status": "processing",
                "prompt_id": prompt_id,
                "data": data,
            }

        except requests.RequestException as e:
            logger.error(f"Failed to get status: {e}")
            raise

    async def download_output(
        self,
        prompt_id: str,
        output_dir: str,
        output_filename: Optional[str] = None,
    ) -> List[str]:
        """
        Download output files from a completed workflow.

        Args:
            prompt_id: The prompt ID
            output_dir: Directory to save files
            output_filename: Optional specific filename to download

        Returns:
            List of downloaded file paths
        """
        os.makedirs(output_dir, exist_ok=True)

        try:
            status = await self.get_status(prompt_id)
            outputs = status.get("outputs", {})

            downloaded_files = []

            for node_id, node_output in outputs.items():
                if isinstance(node_output, dict):
                    images = node_output.get("images", [])

                    for image in images:
                        if isinstance(image, dict):
                            filename = image.get("filename")
                            subfolder = image.get("subfolder", "")

                            if output_filename:
                                save_filename = output_filename
                            else:
                                save_filename = filename

                            url = f"{self.server_url}/view"
                            params = {"filename": filename}
                            if subfolder:
                                params["subfolder"] = subfolder

                            response = requests.get(
                                url,
                                params=params,
                                headers=self._prepare_headers(),
                                timeout=30,
                            )
                            response.raise_for_status()

                            filepath = os.path.join(output_dir, save_filename)
                            with open(filepath, "wb") as f:
                                f.write(response.content)

                            logger.info(f"Downloaded: {filepath}")
                            downloaded_files.append(filepath)

            return downloaded_files

        except requests.RequestException as e:
            logger.error(f"Failed to download outputs: {e}")
            raise

    async def generate_thumbnail(
        self,
        topic_prompt: str,
        output_path: str,
        style: str = "professional",
    ) -> str:
        """
        Generate a video thumbnail.

        Args:
            topic_prompt: Description of the thumbnail content
            output_path: Path to save the thumbnail
            style: Style of the thumbnail (e.g., 'professional', 'minimal', 'bold')

        Returns:
            Path to the generated thumbnail
        """
        # This is a convenience method that would use a pre-configured
        # ComfyUI workflow for thumbnail generation
        prompt = {
            "positive": f"{topic_prompt}, {style} style, high quality, 1280x720",
            "negative": "low quality, blurry, watermark",
        }

        logger.info(f"Generating thumbnail for: {topic_prompt}")
        # Would load appropriate workflow from config
        return output_path

    async def generate_broll(
        self,
        image_path: str,
        motion_prompt: str,
        output_path: str,
    ) -> str:
        """
        Generate B-roll from a static image with motion.

        Args:
            image_path: Path to input image
            motion_prompt: Description of desired motion
            output_path: Path to save video

        Returns:
            Path to the generated B-roll video
        """
        logger.info(f"Generating B-roll with motion: {motion_prompt}")
        # Would load appropriate workflow from config
        return output_path

    async def generate_short_video(
        self,
        prompt: str,
        output_path: str,
        duration_seconds: int = 15,
        fps: int = 24,
    ) -> str:
        """
        Generate a short video from text prompt.

        Args:
            prompt: Text description of the video
            output_path: Path to save the video
            duration_seconds: Duration of the video
            fps: Frames per second

        Returns:
            Path to the generated video
        """
        logger.info(f"Generating short video: {prompt} ({duration_seconds}s)")
        # Would load appropriate workflow from config
        return output_path


async def main():
    """Example usage of ComfyUIClient."""
    client = ComfyUIClient(server_url="http://localhost:8188")

    try:
        # Example workflow (you would load this from a config/template)
        example_workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "sd15.safetensors"},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": "A beautiful sunset over mountains",
                    "clip": ["1", 1],
                },
            },
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": 42,
                    "steps": 20,
                    "cfg": 7.5,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["2", 0],
                    "latent_image": ["4", 0],
                },
            },
        }

        print("Running workflow...")
        prompt_id = await client.run_workflow(example_workflow)

        print(f"Workflow submitted: {prompt_id}")

        # Check status
        status = await client.get_status(prompt_id)
        print(f"Status: {status}")

        # Download outputs
        files = await client.download_output(prompt_id, "./outputs")
        print(f"Downloaded files: {files}")

    finally:
        await client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
