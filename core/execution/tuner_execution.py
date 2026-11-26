"""
Tuner Execution Manager - Coordinates LLM finetuning workflow
Handles R2 storage, Modal finetuning, and serving URL management

Two entry points:
1. process_training_data() - Called by DataExecutor after JSONL generation
2. get_serving_url() - Called by ChatbotExecutor to retrieve Modal endpoint

Architecture:
- DataExecutor generates JSONL Ã¢â€ â€™ calls process_training_data()
- tuner_execution uploads to R2, triggers Modal, stores URL
- ChatbotExecutor calls get_serving_url() Ã¢â€ â€™ receives Modal endpoint
- Widget generation happens with correct URL embedded
"""

import os
import asyncio
import logging
import httpx
import boto3
from botocore.client import Config
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path


class ModalTunerClient:
    """
    Manages Modal operations for Tuner workflow:
    - Upload training data to Cloudflare R2
    - Trigger Modal finetuning jobs
    - Construct serving URLs for deployed models
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        
        # Modal API credentials from environment
        self.modal_token_id = os.getenv("MODAL_TOKEN_ID")
        self.modal_token_secret = os.getenv("MODAL_TOKEN_SECRET")
        self.modal_workspace = os.getenv("MODAL_WORKSPACE", "tuner")
        
        # Cloudflare R2 credentials
        self.r2_access_key = os.getenv("R2_ACCESS_KEY")
        self.r2_secret_key = os.getenv("R2_SECRET_KEY")
        self.r2_bucket = os.getenv("R2_BUCKET", "tuner-training-data")
        self.r2_endpoint = os.getenv("R2_ENDPOINT")
        
        # Modal API base URL
        self.modal_api_base = "https://api.modal.com/v1"
        
        if not all([self.modal_token_id, self.modal_token_secret]):
            self.logger.warning("Modal credentials not configured - Tuner workflow will fail")
        
        if not all([self.r2_access_key, self.r2_secret_key, self.r2_endpoint]):
            self.logger.warning("R2 credentials not configured - Upload will fail")

    async def upload_training_data(
        self, 
        local_jsonl_path: str, 
        customer_id: str
    ) -> str:
        """
        Upload JSONL training data to Cloudflare R2.
        Returns public R2 URL for Modal to download.
        """
        try:
            # Configure R2 client (S3-compatible)
            s3_client = boto3.client(
                's3',
                endpoint_url=self.r2_endpoint,
                aws_access_key_id=self.r2_access_key,
                aws_secret_access_key=self.r2_secret_key,
                config=Config(signature_version='s3v4')
            )
            
            # Generate unique object key
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            object_key = f"customers/{customer_id}/training_data_{timestamp}.jsonl"
            
            # Upload file
            self.logger.info(f"Uploading training data to R2: {object_key}")
            
            with open(local_jsonl_path, 'rb') as f:
                s3_client.upload_fileobj(
                    f,
                    self.r2_bucket,
                    object_key,
                    ExtraArgs={'ContentType': 'application/jsonlines'}
                )
            
            # Generate R2 URL
            r2_url = f"{self.r2_endpoint}/{self.r2_bucket}/{object_key}"
            
            self.logger.info(f"Ã¢Å“â€¦ Training data uploaded: {r2_url}")
            return r2_url
            
        except Exception as e:
            self.logger.error(f"Failed to upload training data: {str(e)}")
            raise Exception(f"R2 upload failed: {str(e)}")

    async def trigger_finetuning(
        self,
        training_data_url: str,
        customer_id: str,
        base_model: str = "Qwen/Qwen2.5-7B-Instruct"
    ) -> Dict[str, Any]:
        """
        Trigger Modal finetuning job.
        This is fire-and-forget - don't await this function.
        Modal will train for 2-3 hours and deploy serving function when complete.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Modal function URL
                function_url = f"https://{self.modal_workspace}--tuner-run-finetuning.modal.run"
                
                payload = {
                    "training_data_url": training_data_url,
                    "customer_id": customer_id,
                    "base_model": base_model,
                    "axolotl_config": {
                        "adapter": "lora",
                        "lora_r": 16,
                        "lora_alpha": 32,
                        "lora_dropout": 0.05,
                        "lora_target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
                        "sequence_len": 2048,
                        "micro_batch_size": 4,
                        "gradient_accumulation_steps": 4,
                        "num_epochs": 3,
                        "learning_rate": 0.0002,
                        "warmup_steps": 100
                    }
                }
                
                headers = {
                    "Authorization": f"Bearer {self.modal_token_id}:{self.modal_token_secret}",
                    "Content-Type": "application/json"
                }
                
                self.logger.info(f"Triggering Modal finetuning for customer: {customer_id}")
                
                response = await client.post(
                    function_url,
                    json=payload,
                    headers=headers
                )
                
                if response.status_code != 200:
                    raise Exception(f"Modal API error: {response.status_code} - {response.text}")
                
                result = response.json()
                
                job_info = {
                    "job_id": result.get("job_id"),
                    "customer_id": customer_id,
                    "status": "training",
                    "started_at": datetime.now().isoformat(),
                    "eta_hours": 2.5,
                    "base_model": base_model,
                    "training_data_url": training_data_url
                }
                
                self.logger.info(f"Ã¢Å“â€¦ Finetuning job started: {job_info['job_id']}")
                return job_info
                
        except Exception as e:
            self.logger.error(f"Failed to trigger finetuning: {str(e)}")
            raise Exception(f"Modal finetuning trigger failed: {str(e)}")

    def construct_serving_url(self, customer_id: str) -> str:
        """
        Construct deterministic serving URL for customer's model.
        This URL will become active once Modal completes training.
        """
        return f"https://{self.modal_workspace}--tuner-modelserving-serve.modal.run"


class TunerExecutionManager:
    """
    Coordinates the complete Tuner workflow between DataExecutor and ChatbotExecutor.
    
    Workflow:
    1. DataExecutor generates JSONL Ã¢â€ â€™ calls process_training_data()
    2. Manager uploads to R2, triggers Modal, stores serving URL
    3. ChatbotExecutor calls get_serving_url() Ã¢â€ â€™ retrieves Modal endpoint
    4. Widget generation happens with correct URL embedded
    """
    
    # Class-level registry for serving URLs (persists across instances)
    _url_registry: Dict[str, str] = {}
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.modal_client = ModalTunerClient(logger=self.logger)
    
    
    def _generate_customer_id(self, task_data: Dict[str, Any]) -> str:
        """
        Generate unique customer ID from task data.
        Uses user_id if available, otherwise timestamp-based.
        """
        user_id = task_data.get("userId", "anonymous")
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        
        # Clean user_id for use in URLs
        clean_user_id = user_id.replace("@", "-").replace(".", "-")
        
        return f"{clean_user_id}-{timestamp}"
    
    async def process_training_data(
        self,
        jsonl_path: str,
        task_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Called by DataExecutor after JSONL generation.
        
        Steps:
        1. Generate customer ID
        2. Generate training examples from Q-A clusters (qa_clusters.json → training_data.jsonl)
        3. Upload JSONL to R2
        4. Construct serving URL (deterministic, no waiting for Modal)
        5. Trigger Modal finetuning (fire-and-forget)
        6. Store URL for ChatbotExecutor retrieval
        
        Returns dict with customer_id and serving_url.
        """
        try:
            # Generate customer ID
            customer_id = self._generate_customer_id(task_data)
            
            self.logger.info(f"Processing training data for customer: {customer_id}")
            
            # Count examples in JSONL file
            num_examples = 0
            try:
                with open(jsonl_path, "r") as f:
                    num_examples = sum(1 for line in f if line.strip())
                self.logger.info(f"Training data contains {num_examples} examples")
            except Exception as e:
                self.logger.warning(f"Could not count examples: {e}")
            
            # Upload to R2
            storage_url = await self.modal_client.upload_training_data(
                jsonl_path, 
                customer_id
            )
            
            # Construct serving URL immediately (before Modal completes)
            serving_url = self.modal_client.construct_serving_url(customer_id)
            
            # Store in registry for ChatbotExecutor
            TunerExecutionManager._url_registry[customer_id] = serving_url
            
            self.logger.info(f"Stored serving URL for {customer_id}: {serving_url}")
            
            # Trigger Modal finetuning (fire-and-forget, don't await)
            asyncio.create_task(
                self.modal_client.trigger_finetuning(
                    training_data_url=storage_url,
                    customer_id=customer_id,
                    base_model="Qwen/Qwen2.5-7B-Instruct"
                )
            )
            
            self.logger.info(f"Modal finetuning triggered for {customer_id} (background task)")
            
            return {
                "customer_id": customer_id,
                "serving_url": serving_url,
                "storage_url": storage_url,
                "num_examples": num_examples,
                "status": "training_initiated"
            }
            
        except Exception as e:
            self.logger.error(f"Error processing training data: {str(e)}")
            raise
    
    def get_serving_url(self, customer_id: str) -> Optional[str]:
        """
        Called by ChatbotExecutor to retrieve Modal serving URL.
        Returns None if customer_id not found.
        """
        url = TunerExecutionManager._url_registry.get(customer_id)
        
        if url:
            self.logger.info(f"Retrieved serving URL for {customer_id}: {url}")
        else:
            self.logger.warning(f"No serving URL found for customer: {customer_id}")
        
        return url
    
    def get_all_customers(self) -> Dict[str, str]:
        """Return all customer_id -> serving_url mappings (for debugging)"""
        return TunerExecutionManager._url_registry.copy()