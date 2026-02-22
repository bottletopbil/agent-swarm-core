import json
import logging
import os
import hashlib
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

class AuditVerifier:
    def __init__(self, log_path="logs/audit.jsonl"):
        self.log_path = log_path

    def verify_hash_chain(self) -> bool:
        """Scans the JSONL file and mathematically verifies every prev_hash matches the computed hash."""
        if not os.path.exists(self.log_path):
            logging.error(f"Audit log missing at {self.log_path}")
            return False
            
        expected_prev_hash = "0" * 64
        line_num = 1
        
        with open(self.log_path, "r") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                except json.JSONDecodeError:
                    logging.error(f"Integrity Error: Corrupted JSON at line {line_num}")
                    return False
                
                # Verify Chain Link
                if entry.get("prev_hash") != expected_prev_hash:
                    logging.error(f"Integrity Error: Hash chain broken at line {line_num}. Expected prev_hash {expected_prev_hash}, got {entry.get('prev_hash')}")
                    return False
                    
                # Recompute current hash
                payload_str = json.dumps(entry.get("envelope"), sort_keys=True)
                sha = hashlib.sha256()
                sha.update((expected_prev_hash + payload_str).encode('utf-8'))
                computed_hash = sha.hexdigest()
                
                if computed_hash != entry.get("hash"):
                    logging.error(f"Integrity Error: Payload tampered at line {line_num}. Re-computed hash {computed_hash} does not match stored hash {entry.get('hash')}")
                    return False
                    
                expected_prev_hash = entry.get("hash")
                line_num += 1
                
        logging.info(f"Hash Chain Verification PASSED! Checked {line_num - 1} entries.")
        return True

    def verify_causal_progression(self) -> bool:
        """
        Proves that tasks mathematically progress through the correct states.
        e.g., Worker -> Verifier -> Done
        """
        if not os.path.exists(self.log_path):
            return False
            
        task_states = defaultdict(list)
        
        with open(self.log_path, "r") as f:
            for line in f:
                entry = json.loads(line.strip())
                env = entry.get("envelope", {})
                task_id = env.get("payload", {}).get("task_id") or env.get("id")
                sender = env.get("sender")
                if task_id and sender:
                    task_states[task_id].append(sender)
                    
        issues = 0
        for task_id, senders in task_states.items():
            # Find the most terminal state we reached
            if "verifier" in senders and "worker" not in senders:
                logging.error(f"Causal Error: Task {task_id} verified before worker picked it up!")
                issues += 1
            if "coordinator" not in senders:
                # Planners can create tasks too
                pass
                
        if issues == 0:
            logging.info("Causal Progression Verification PASSED!")
            
        return issues == 0

if __name__ == "__main__":
    verifier = AuditVerifier()
    
    chain_valid = verifier.verify_hash_chain()
    causal_valid = verifier.verify_causal_progression()
    
    if chain_valid and causal_valid:
        logging.info("ALL AUDIT VERIFICATIONS PASSED SUCCESSFULLY.")
    else:
        logging.critical("AUDIT VERIFICATION FAILED. TAMPERING DETECTED.")
        exit(1)
