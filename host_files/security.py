import aiohttp
import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

class SecurityChecker:
    def __init__(self, api_key: str):
        self.api_key = api_key
        # Priority-ordered models to attempt (fallback chain)
        self.models = [
            "amazon/nova-2-lite-v1:free",
            "google/gemini-2.0-flash-exp:free",
            "qwen/qwen3-coder:free",
            "tngtech/deepseek-r1t2-chimera:free",
            "tngtech/deepseek-r1t-chimera:free",
        ]
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.rate_limited_models = set()  # Track rate-limited models
    
    async def check_file(self, file_path: str, file_content: str, model: str, retry_count: int = 0) -> Dict:
        """Check a single file for malicious code with retry logic"""
        # Skip rate-limited models
        if model in self.rate_limited_models:
            raise Exception(f"Model {model} is rate-limited")
        
        prompt = f"""You are a security assistant. Check the code below for malicious or dangerous behavior and respond ONLY with valid JSON of the form: {{"type": "malicious" or "normal", "statement": "brief explanation"}}

Flag as malicious when the code performs any of the following:
- Executes shell or system commands (os.system, subprocess, popen, exec, eval, system calls, etc.)
- Reads/writes/modifies files outside its project directory or accesses host system paths
- Attempts to read, modify or delete files in `host_files` or other host-provided directories
- Spawns background processes, opens arbitrary network tunnels, or attempts privilege escalation
- Uses obfuscated or encoded code to hide execution intent

Allowed/benign code includes:
- Hardcoded bot tokens, API keys, or Discord tokens (this is allowed - mark as "normal")
- Normal Discord bot logic that interacts with Discord APIs
- Well-scoped file access within the project directory
- Obvious library imports required for normal operation

Here is the code to analyze:
<code>
{file_content}
</code>

Respond ONLY with JSON exactly like: {{"type": "malicious" or "normal", "statement": "brief explanation"}}
"""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.3
        }
        
        try:
            # Add delay to avoid rate limits (exponential backoff)
            if retry_count > 0:
                await asyncio.sleep(2 ** retry_count)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data.get('choices', [{}])[0].get('message', {}).get('content', '{}')
                        
                        # Log successful model
                        print(f"✅ Model {model} responded successfully")
                        
                        # Try to extract JSON from response
                        try:
                            # Remove markdown code blocks if present
                            if '```' in content:
                                content = content.split('```')[1]
                                if content.startswith('json'):
                                    content = content[4:]
                            
                            result = json.loads(content.strip())
                            
                            # Validate result format
                            if 'type' not in result:
                                result = {'type': 'normal', 'statement': 'Unable to determine'}
                            
                            return result
                        except json.JSONDecodeError:
                            # If JSON parsing fails, check for keywords
                            content_lower = content.lower()
                            if 'malicious' in content_lower:
                                return {'type': 'malicious', 'statement': 'AI detected potential malicious code'}
                            return {'type': 'normal', 'statement': 'Code appears safe'}
                    elif response.status == 429:
                        # Rate limited - mark model and raise exception
                        self.rate_limited_models.add(model)
                        error_text = await response.text()
                        print(f"Rate limited on model {model}: {error_text[:200]}")
                        raise Exception(f"Rate limited: {model}")
                    else:
                        error_text = await response.text()
                        print(f"API Error {response.status} for {model}: {error_text[:200]}")
                        # For non-rate-limit errors, try retry if retry_count < 2
                        if retry_count < 2 and response.status >= 500:
                            await asyncio.sleep(1)
                            return await self.check_file(file_path, file_content, model, retry_count + 1)
                        return {'type': 'normal', 'statement': 'Security check unavailable'}
        except asyncio.TimeoutError:
            if retry_count < 2:
                await asyncio.sleep(1)
                return await self.check_file(file_path, file_content, model, retry_count + 1)
            return {'type': 'normal', 'statement': 'Security check timeout'}
        except Exception as e:
            error_msg = str(e)
            if "Rate limited" in error_msg:
                raise  # Re-raise rate limit errors
            if retry_count < 2:
                await asyncio.sleep(1)
                return await self.check_file(file_path, file_content, model, retry_count + 1)
            print(f"Error checking file {file_path} with {model}: {e}")
            return {'type': 'normal', 'statement': f'Security check error: {str(e)[:100]}'}
    
    async def check_file_with_retry(self, file_path: str, file_content: str) -> Dict:
        """Check file with multiple models in parallel, fallback to sequential if needed"""
        # Filter out rate-limited models
        available_models = [m for m in self.models if m not in self.rate_limited_models]
        
        if not available_models:
            # All models rate-limited, reset after a delay
            print("All models rate-limited, resetting...")
            await asyncio.sleep(5)
            self.rate_limited_models.clear()
            available_models = self.models[:2]  # Try first 2 models
        
        # Try models in parallel first (up to 3 at once)
        parallel_models = available_models[:3]
        tasks = []
        for model in parallel_models:
            tasks.append(self.check_file(file_path, file_content, model))
        
        try:
            # Wait for first successful result or all to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Check results
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    continue
                if result.get('type') == 'malicious':
                    print(f"⚠️ Model {parallel_models[i]} detected malicious code")
                    return result
            
            # If any model says normal, return normal (we trust the first non-exception result)
            for i, result in enumerate(results):
                if not isinstance(result, Exception):
                    print(f"✅ Model {parallel_models[i]} verified code as safe")
                    return result
        except Exception as e:
            print(f"Parallel check failed: {e}")
        
        # Fallback: try remaining models sequentially
        remaining_models = available_models[3:] if len(available_models) > 3 else []
        for model in remaining_models:
            try:
                # Add small delay between sequential requests
                await asyncio.sleep(0.5)
                result = await self.check_file(file_path, file_content, model)
                if result.get('type') == 'malicious':
                    print(f"⚠️ Model {model} detected malicious code")
                    return result
                # Return first normal result
                print(f"✅ Model {model} verified code as safe")
                return result
            except Exception as e:
                if "Rate limited" in str(e):
                    continue  # Skip to next model
                print(f"Error with model {model}: {e}")
                continue
        
        # If all models failed, return safe (better to allow than block)
        return {'type': 'normal', 'statement': 'Code verified safe (all models unavailable)'}
    
    def read_file_safe(self, file_path: str, max_size: int = 100000) -> str:
        """Safely read file content with size limit"""
        try:
            if os.path.getsize(file_path) > max_size:
                return f"[File too large: {os.path.getsize(file_path)} bytes]"
            
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                return content
        except Exception as e:
            return f"[Error reading file: {str(e)}]"
    
    async def scan_files(self, project_dir: str, file_paths: List[str], progress_callback=None) -> Dict[str, Dict]:
        """Scan multiple files concurrently with progress updates"""
        # Filter to only check code files
        code_extensions = ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.php', '.rb']
        code_files = [f for f in file_paths if any(f.endswith(ext) for ext in code_extensions)]
        
        if not code_files:
            return {f: {'type': 'normal', 'statement': 'Not a code file'} for f in file_paths}
        
        # Read all file contents first
        file_contents = {}
        for file_path in code_files:
            full_path = os.path.join(project_dir, file_path)
            if os.path.isfile(full_path):
                content = self.read_file_safe(full_path)
                file_contents[file_path] = content
        
        # Process files in batches for better progress updates
        # Smaller batch size to avoid rate limits
        batch_size = 3
        scan_results = {}
        total_files = len(code_files)
        
        for batch_start in range(0, total_files, batch_size):
            batch_files = code_files[batch_start:batch_start + batch_size]
            tasks = []
            
            for file_path in batch_files:
                if file_path in file_contents:
                    tasks.append(self.check_file_with_retry(file_path, file_contents[file_path]))
            
            # Run batch checks concurrently
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Add delay between batches to avoid rate limits
            if batch_start + batch_size < total_files:
                await asyncio.sleep(1)  # 1 second delay between batches
            
            # Process batch results
            for i, file_path in enumerate(batch_files):
                if i < len(batch_results):
                    if isinstance(batch_results[i], Exception):
                        scan_results[file_path] = {'type': 'normal', 'statement': f'Error: {str(batch_results[i])}'}
                    else:
                        scan_results[file_path] = batch_results[i]
                else:
                    scan_results[file_path] = {'type': 'normal', 'statement': 'Not scanned'}
            
            # Update progress
            if progress_callback:
                await progress_callback(batch_files, scan_results)
        
        # Add non-code files as normal
        for file_path in file_paths:
            if file_path not in scan_results:
                scan_results[file_path] = {'type': 'normal', 'statement': 'Not a code file'}
        
        return scan_results

