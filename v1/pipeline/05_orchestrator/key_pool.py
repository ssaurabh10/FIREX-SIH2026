# -*- coding: utf-8 -*-
import sys, io
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

"""
Round-robin API Key Manager with automatic failover across the key pool.
"""

import requests
import json
import re

class KeyPoolManager:
    def __init__(self, api_keys, model_name):
        self.api_keys = [k.strip() for k in api_keys if k.strip()]
        self.model_name = model_name
        self.current_idx = 0
        
    def get_current_key(self):
        return self.api_keys[self.current_idx]
        
    def rotate_key(self):
        old_idx = self.current_idx
        self.current_idx = (self.current_idx + 1) % len(self.api_keys)
        print(f"    [Key Rotator] Rotating Key #{old_idx + 1} -> Key #{self.current_idx + 1}")
        return self.get_current_key()
        
    def call_minimax_vision(self, prompt, b64_image, max_retries=None):
        if max_retries is None:
            max_retries = len(self.api_keys) * 2
            
        attempts = 0
        while attempts < max_retries:
            attempts += 1
            key = self.get_current_key()
            key_id = f"Key #{self.current_idx + 1} ({key[:14]}...)"
            
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{b64_image}"
                                }
                            }
                        ]
                    }
                ],
                "reasoning": {"enabled": True},
                "temperature": 0.1,
                "max_tokens": 1600
            }
            
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/FIREX-SIH2026",
                "X-Title": "FIREX Thermal Intelligence Pipeline"
            }
            
            try:
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    choice = data["choices"][0]["message"]
                    content = choice.get("content", "")
                    reasoning = choice.get("reasoning_details") or choice.get("reasoning", "")
                    
                    clean = re.sub(r"^```json\s*", "", content, flags=re.MULTILINE)
                    clean = re.sub(r"^```\s*", "", clean, flags=re.MULTILINE)
                    match = re.search(r"\{.*\}", clean, re.DOTALL)
                    if match:
                        clean = match.group(0)
                        
                    parsed = json.loads(clean)
                    # Advance key for next call
                    self.rotate_key()
                    return parsed, key_id, reasoning
                elif resp.status_code in [429, 401, 402, 403]:
                    print(f"    [!] {key_id} returned HTTP {resp.status_code}. Auto-failing over...")
                    self.rotate_key()
                else:
                    print(f"    [!] Error from {key_id} (HTTP {resp.status_code}): {resp.text[:100]}")
                    self.rotate_key()
            except Exception as e:
                print(f"    [!] Network/Parse error with {key_id}: {e}")
                self.rotate_key()
                
        return None, "All keys exhausted", None
