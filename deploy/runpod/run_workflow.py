#!/usr/bin/env python3
"""
RunPod ComfyUI Workflow Runner
Manages ComfyUI workflow execution on RunPod serverless and on-demand GPUs.
Includes pod lifecycle management, job queuing, and automatic cost optimization.
"""

import json
import time
import requests
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
import os
import sys

# RunPod SDK (install with: pip install runpod)
try:
    import runpod
except ImportError:
    print("Error: runpod library not installed. Install with: pip install runpod")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GPUType(Enum):
    """GPU types available on RunPod"""
    RTX_4090 = "RTX4090"
    RTX_6000_ADA = "RTX6000Ada"
    L40 = "L40"
    L40S = "L40S"
    A100_40GB = "A100-40gb"
    A100_80GB = "A100-80gb"
    H100 = "H100"


class PodStatus(Enum):
    """Pod lifecycle states"""
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    TERMINATED = "TERMINATED"


@dataclass
class PodConfig:
    """Configuration for RunPod instance"""
    gpu_type: GPUType = GPUType.RTX_4090
    gpu_count: int = 1
    volume_size_gb: int = 50
    template_id: str = "runpod-comfyui"  # Pre-built ComfyUI template
    max_idle_minutes: int = 10


@dataclass
class WorkflowJob:
    """ComfyUI workflow job"""
    job_id: str
    workflow: Dict[str, Any]
    prompt_id: Optional[str] = None
    status: str = "pending"
    result: Optional[Dict[str, Any]] = None
    created_at: float = 0
    completed_at: Optional[float] = None


class RunPodManager:
    """Manages RunPod pod lifecycle and ComfyUI API interaction"""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize RunPod manager.

        Args:
            api_key: RunPod API key (defaults to RUNPOD_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("RUNPOD_API_KEY")
        if not self.api_key:
            raise ValueError("RUNPOD_API_KEY environment variable not set")

        self.pod_id: Optional[str] = None
        self.pod_url: Optional[str] = None
        self.comfyui_api_url: Optional[str] = None
        self.idle_timeout_minutes = 10
        self.last_activity_time = time.time()
        self.job_queue: List[WorkflowJob] = []

    def create_pod(self, config: PodConfig) -> str:
        """
        Create and start a new RunPod GPU instance.

        Args:
            config: Pod configuration

        Returns:
            Pod ID
        """
        logger.info(f"Creating RunPod with {config.gpu_type.value} GPU...")

        # Use RunPod SDK to create pod
        client = runpod.api.create_pod(
            name=f"comfyui-{int(time.time())}",
            image_name="runpod/comfyui",  # Use pre-built ComfyUI image
            gpu_count=config.gpu_count,
            volume_size_gb=config.volume_size_gb,
            gpu_type_id=config.gpu_type.value,
            api_key=self.api_key,
        )

        self.pod_id = client["id"]
        logger.info(f"Pod created: {self.pod_id}")

        # Wait for pod to be running
        self._wait_for_pod_running(timeout_seconds=120)

        # Get pod details and API URL
        pod_info = self.get_pod_info()
        self.pod_url = f"https://{pod_info['podFqdn']}"
        self.comfyui_api_url = f"{self.pod_url}/api"

        logger.info(f"Pod running at: {self.pod_url}")
        return self.pod_id

    def get_pod_info(self) -> Dict[str, Any]:
        """Get current pod information"""
        if not self.pod_id:
            raise ValueError("No pod created yet. Call create_pod() first.")

        client = runpod.api.get_pod(self.pod_id, self.api_key)
        return client

    def _wait_for_pod_running(self, timeout_seconds: int = 120):
        """Wait for pod to reach RUNNING state"""
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            try:
                pod_info = self.get_pod_info()
                if pod_info.get("desiredStatus") == "RUNNING":
                    logger.info("Pod is running")
                    return
            except Exception as e:
                logger.debug(f"Pod not ready yet: {e}")

            time.sleep(5)

        raise TimeoutError(f"Pod did not reach RUNNING state within {timeout_seconds}s")

    def check_pod_health(self) -> bool:
        """Check if ComfyUI API is responding"""
        if not self.comfyui_api_url:
            return False

        try:
            response = requests.get(
                f"{self.comfyui_api_url}/system_stats",
                timeout=5
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def submit_workflow(self, workflow: Dict[str, Any]) -> str:
        """
        Submit a ComfyUI workflow for execution.

        Args:
            workflow: ComfyUI workflow JSON

        Returns:
            Prompt/Job ID
        """
        if not self.comfyui_api_url:
            raise ValueError("ComfyUI API URL not configured. Ensure pod is running.")

        logger.info("Submitting workflow to ComfyUI...")
        self.last_activity_time = time.time()

        try:
            response = requests.post(
                f"{self.comfyui_api_url}/prompt",
                json=workflow,
                timeout=30
            )
            response.raise_for_status()

            prompt_id = response.json()["prompt_id"]
            logger.info(f"Workflow submitted with prompt ID: {prompt_id}")
            return prompt_id

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to submit workflow: {e}")
            raise

    def get_job_status(self, prompt_id: str) -> Dict[str, Any]:
        """
        Get the status of a submitted workflow.

        Args:
            prompt_id: The prompt/job ID from submit_workflow

        Returns:
            Job status information
        """
        if not self.comfyui_api_url:
            raise ValueError("ComfyUI API URL not configured.")

        try:
            response = requests.get(
                f"{self.comfyui_api_url}/prompt/{prompt_id}",
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "status": "completed" if data.get("outputs") else "processing",
                    "output": data.get("outputs"),
                    "messages": data.get("messages")
                }
            elif response.status_code == 404:
                return {"status": "not_found"}
            else:
                return {"status": "error", "error": response.text}

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get job status: {e}")
            return {"status": "error", "error": str(e)}

    def download_result(self, prompt_id: str, output_dir: str = "./output") -> List[str]:
        """
        Download workflow results.

        Args:
            prompt_id: The prompt ID to download results for
            output_dir: Directory to save results

        Returns:
            List of downloaded file paths
        """
        os.makedirs(output_dir, exist_ok=True)
        self.last_activity_time = time.time()

        # Get job history
        if not self.comfyui_api_url:
            raise ValueError("ComfyUI API URL not configured.")

        try:
            response = requests.get(
                f"{self.comfyui_api_url}/history/{prompt_id}",
                timeout=10
            )
            response.raise_for_status()

            history = response.json()
            downloaded_files = []

            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})

                # Download each output file
                for node_id, node_output in outputs.items():
                    if isinstance(node_output, dict) and "images" in node_output:
                        for image in node_output["images"]:
                            file_url = f"{self.pod_url}/view?filename={image['filename']}"
                            response = requests.get(file_url, timeout=30)

                            if response.status_code == 200:
                                file_path = os.path.join(output_dir, image["filename"])
                                with open(file_path, "wb") as f:
                                    f.write(response.content)
                                downloaded_files.append(file_path)
                                logger.info(f"Downloaded: {file_path}")

            return downloaded_files

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download results: {e}")
            return []

    def poll_until_complete(self, prompt_id: str, timeout_seconds: int = 3600,
                           check_interval: int = 10) -> Dict[str, Any]:
        """
        Poll job status until completion.

        Args:
            prompt_id: The prompt ID to monitor
            timeout_seconds: Maximum time to wait
            check_interval: Seconds between status checks

        Returns:
            Final job status
        """
        logger.info(f"Polling job status (timeout: {timeout_seconds}s)...")
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            status = self.get_job_status(prompt_id)

            if status["status"] == "completed":
                logger.info("Job completed!")
                return status

            elif status["status"] == "processing":
                elapsed = int(time.time() - start_time)
                logger.info(f"Still processing... ({elapsed}s elapsed)")

            time.sleep(check_interval)

        raise TimeoutError(f"Job did not complete within {timeout_seconds}s")

    def stop_pod(self, keep_volume: bool = True):
        """
        Stop the RunPod instance to save costs.

        Args:
            keep_volume: Keep the volume data when stopping
        """
        if not self.pod_id:
            logger.warning("No active pod to stop")
            return

        logger.info(f"Stopping pod {self.pod_id}...")

        try:
            runpod.api.stop_pod(
                self.pod_id,
                self.api_key
            )
            logger.info("Pod stopped successfully")
            self.pod_id = None
            self.comfyui_api_url = None

        except Exception as e:
            logger.error(f"Failed to stop pod: {e}")

    def terminate_pod(self):
        """Permanently terminate the pod (cannot be restarted)"""
        if not self.pod_id:
            logger.warning("No active pod to terminate")
            return

        logger.info(f"Terminating pod {self.pod_id}...")

        try:
            runpod.api.terminate_pod(
                self.pod_id,
                self.api_key
            )
            logger.info("Pod terminated")
            self.pod_id = None
            self.comfyui_api_url = None

        except Exception as e:
            logger.error(f"Failed to terminate pod: {e}")

    def check_idle_timeout(self):
        """Check if pod has been idle and stop it to save costs"""
        if not self.pod_id:
            return

        idle_time = (time.time() - self.last_activity_time) / 60
        if idle_time > self.idle_timeout_minutes:
            logger.warning(f"Pod idle for {idle_time:.1f} minutes. Stopping to save costs...")
            self.stop_pod()


def load_workflow_template(template_path: str) -> Dict[str, Any]:
    """Load a ComfyUI workflow template from JSON file"""
    try:
        with open(template_path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load workflow template: {e}")
        raise


# Example usage
def example_workflow():
    """
    Example: Run a complete video generation workflow.

    This demonstrates:
    1. Creating a pod with specific GPU
    2. Submitting a ComfyUI workflow
    3. Polling for completion
    4. Downloading results
    5. Stopping the pod
    """
    try:
        # Initialize manager
        manager = RunPodManager()

        # Create pod configuration
        config = PodConfig(
            gpu_type=GPUType.RTX_4090,
            gpu_count=1,
            volume_size_gb=50,
        )

        # Create pod (costs start accumulating)
        pod_id = manager.create_pod(config)
        logger.info(f"Created pod: {pod_id}")

        # Wait for ComfyUI to be ready
        logger.info("Waiting for ComfyUI API to be ready...")
        for attempt in range(30):  # Wait up to 2.5 minutes
            if manager.check_pod_health():
                logger.info("ComfyUI API is ready!")
                break
            time.sleep(5)
        else:
            raise RuntimeError("ComfyUI API never became ready")

        # Load or construct workflow
        # For this example, we'll create a simple text-to-image workflow
        workflow = {
            "1": {
                "inputs": {"text": "A beautiful sunset over mountains", "clip": ["49", 0]},
                "class_type": "CLIPTextEncode"
            },
            "2": {
                "inputs": {"text": "bad quality, blurry", "clip": ["49", 0]},
                "class_type": "CLIPTextEncode"
            },
            "3": {
                "inputs": {"seed": 12345, "steps": 20, "cfg": 7.0,
                          "sampler_name": "euler", "scheduler": "normal",
                          "denoise": 1.0, "model": ["49", 0],
                          "positive": ["1", 0], "negative": ["2", 0],
                          "latent_image": ["7", 0]},
                "class_type": "KSampler"
            },
            "8": {
                "inputs": {"samples": ["3", 0], "vae": ["49", 2]},
                "class_type": "VAEDecode"
            },
            "9": {
                "inputs": {"images": ["8", 0], "filename_prefix": "output"},
                "class_type": "SaveImage"
            },
            # Add more nodes as needed for your specific workflow
        }

        # Submit workflow
        prompt_id = manager.submit_workflow(workflow)

        # Poll for completion
        status = manager.poll_until_complete(prompt_id, timeout_seconds=3600)
        logger.info(f"Job status: {status}")

        # Download results
        output_files = manager.download_result(prompt_id, "./output")
        logger.info(f"Downloaded {len(output_files)} files")

        # Stop pod to save costs
        manager.stop_pod()
        logger.info("Pod stopped. Charges have stopped accumulating.")

    except Exception as e:
        logger.error(f"Error in workflow: {e}")
        # Make sure to stop pod even if error occurs
        if 'manager' in locals():
            manager.stop_pod()
        raise


if __name__ == "__main__":
    # Ensure API key is set
    if not os.getenv("RUNPOD_API_KEY"):
        print("Error: RUNPOD_API_KEY environment variable not set")
        print("Set it with: export RUNPOD_API_KEY='your-api-key'")
        sys.exit(1)

    # Run example
    example_workflow()
