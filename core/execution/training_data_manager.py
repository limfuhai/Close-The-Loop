"""
Training Data Manager - Converts simplified cluster format to full JSONL
Similar to script_manager.py but for training data expansion

Handles the conversion from DataExecutor's token-efficient cluster format
to the full JSONL format required by Modal/Axolotl training.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Tuple


class TrainingDataManager:
    """
    Manages training data format conversion.
    Converts simplified cluster format to full JSONL format for Modal.
    
    Flow:
    1. DataExecutor generates simplified clusters (token-efficient)
    2. TrainingDataManager expands to full format (Modal-compatible)
    3. tuner_execution.py uploads to R2 and triggers training
    """
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
    
    def expand_clusters_to_jsonl(
        self, 
        cluster_file_path: str,
        company_name: str = "Customer"
    ) -> Tuple[str, int]:
        """
        Expand simplified cluster format to full training_data.jsonl.
        
        Input format (one line per cluster in any .jsonl file):
        {"questions": ["Q1", "Q2", "Q3"], "answer": "A"}
        
        Output format (one line per example in training_data.jsonl):
        {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}
        
        Args:
            cluster_file_path: Path to the cluster JSONL file from DataExecutor
            company_name: Company name for system message
            
        Returns:
            Tuple[str, int]: (path to training_data.jsonl, number of examples)
        """
        cluster_path = Path(cluster_file_path)
        
        self.logger.info(f"Reading clusters from: {cluster_path.name}")
        
        # Read clusters from JSONL
        clusters = []
        with open(cluster_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        clusters.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        self.logger.warning(f"Skipping invalid JSON line: {e}")
                        continue
        
        if not clusters:
            raise ValueError("No valid clusters found in file")
        
        self.logger.info(f"✅ Loaded {len(clusters)} clusters")
        
        # System message (same for all examples)
        system_message = f"You are {company_name} assistant"
        
        # Expand clusters into individual training examples
        examples = []
        
        for i, cluster in enumerate(clusters):
            questions = cluster.get("questions", [])
            answer = cluster.get("answer", "")
            
            if not questions:
                self.logger.warning(f"Cluster {i+1} has no questions, skipping")
                continue
            
            if not answer:
                self.logger.warning(f"Cluster {i+1} has no answer, skipping")
                continue
            
            # Create one example per question variation
            for question in questions:
                examples.append({
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": answer}
                    ]
                })
        
        self.logger.info(f"Generated {len(examples)} examples from {len(clusters)} clusters")
        
        # Deduplicate questions (case-insensitive)
        unique_examples = []
        seen_questions = set()
        
        for ex in examples:
            question = ex["messages"][1]["content"].lower().strip()
            if question not in seen_questions:
                unique_examples.append(ex)
                seen_questions.add(question)
        
        duplicates_removed = len(examples) - len(unique_examples)
        if duplicates_removed > 0:
            self.logger.info(f"Removed {duplicates_removed} duplicate questions")
        
        # Write to training_data.jsonl in the same directory
        output_path = cluster_path.parent / "training_data.jsonl"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for example in unique_examples:
                f.write(json.dumps(example, ensure_ascii=False) + '\n')
        
        self.logger.info(f"✅ Created training_data.jsonl with {len(unique_examples)} unique examples")
        
        return str(output_path), len(unique_examples)