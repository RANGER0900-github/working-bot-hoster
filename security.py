import aiohttp
import asyncio
import json
import os
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Callable
from pathlib import Path
from config import SECURITY_SCAN_TIMEOUT, SECURITY_BATCH_SIZE, MAX_FILE_SIZE

logger = logging.getLogger(__name__)

class SecurityChecker:
    """Security checking module using AI models to detect malicious code."""
    
    def __init__(self, api_key: str):
        """
        Initialize SecurityChecker.
        
        Args:
            api_key: OpenRouter API key
        """
        if not api_key:
            raise ValueError("API key is required")
        
        self.api_key = api_key
        # Priority-ordered models to attempt (fallback chain)
        self.models = [
            "amazon/nova-2-lite-v1:free",
            "google/gemini-2.0-flash-exp:free",
            "qwen/qwen3-coder:free",
            "tngtech/deepseek-r1t2-chimera:free",
            "tngtech/deepseek-r1t-chimera:free"
        ]
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.rate_limited_models = set()
        logger.info("SecurityChecker initialized")
    
    async def check_file(self, file_path: str, file_content: str, model: str) -> Dict:
        """
        Check a single file for malicious code.
        
        Args:
            file_path: Path to the file being checked
            file_content: Content of the file
            model: AI model to use for checking
            
        Returns:
            dict: {"type": "malicious" or "normal", "statement": "explanation"}
        """
        # Skip rate-limited models
        if model in self.rate_limited_models:
            logger.debug(f"Skipping rate-limited model: {model}")
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
            "Content-Type": "application/json",
            # Recommended headers from OpenRouter docs
            "HTTP-Referer": "https://discord.com",
            "X-Title": "Working Bot Hoster"
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
            logger.debug(f"Checking file {file_path} with model {model}")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=SECURITY_SCAN_TIMEOUT)
                ) as response:
                    if response.status == 200:
                        try:
                            data = await response.json()
                            content = data.get('choices', [{}])[0].get('message', {}).get('content', '{}')
                            
                            # Try to extract JSON from response
                            try:
                                # Remove markdown code blocks if present
                                if '```' in content:
                                    parts = content.split('```')
                                    if len(parts) > 1:
                                        content = parts[1]
                                        if content.startswith('json'):
                                            content = content[4:]
                                
                                result = json.loads(content.strip())
                                
                                # Validate result format
                                if 'type' not in result:
                                    logger.warning(f"Invalid result format from model {model} for {file_path}")
                                    result = {'type': 'normal', 'statement': 'Unable to determine'}
                                
                                logger.debug(f"Security check result for {file_path}: {result['type']}")
                                return result
                            except json.JSONDecodeError as e:
                                logger.warning(f"JSON decode error for {file_path} with model {model}: {str(e)}")
                                # If JSON parsing fails, check for keywords
                                content_lower = content.lower()
                                if 'malicious' in content_lower:
                                    logger.warning(f"Malicious keyword detected in response for {file_path}")
                                    return {'type': 'malicious', 'statement': 'AI detected potential malicious code'}
                                return {'type': 'normal', 'statement': 'Code appears safe'}
                        except json.JSONDecodeError as e:
                            logger.error(f"Error parsing API response for {file_path}: {str(e)}")
                            return {'type': 'normal', 'statement': 'Security check response parsing error'}
                    elif response.status == 429:
                        # Rate limited
                        logger.warning(f"Rate limited by model {model}")
                        self.rate_limited_models.add(model)
                        error_text = await response.text()
                        logger.debug(f"Rate limit response: {error_text}")
                        raise Exception(f"Rate limited by {model}")
                    else:
                        error_text = await response.text()
                        logger.error(f"API Error {response.status} for {file_path}: {error_text[:200]}")
                        return {'type': 'normal', 'statement': f'Security check unavailable (HTTP {response.status})'}
        except asyncio.TimeoutError:
            logger.warning(f"Timeout checking file {file_path} with model {model}")
            return {'type': 'normal', 'statement': 'Security check timeout'}
        except aiohttp.ClientError as e:
            logger.error(f"Client error checking file {file_path}: {str(e)}", exc_info=True)
            return {'type': 'normal', 'statement': f'Security check network error: {str(e)[:50]}'}
        except Exception as e:
            logger.error(f"Error checking file {file_path} with model {model}: {str(e)}", exc_info=True)
            return {'type': 'normal', 'statement': f'Security check error: {str(e)[:50]}'}
    
    async def check_file_with_retry(self, file_path: str, file_content: str) -> Dict:
        """
        Check file with multiple models and retry logic.
        
        Args:
            file_path: Path to the file being checked
            file_content: Content of the file
            
        Returns:
            dict: Security check result
        """
        logger.debug(f"Checking file {file_path} with retry logic")
        
        # Try with different models
        for model in self.models:
            if model in self.rate_limited_models:
                logger.debug(f"Skipping rate-limited model: {model}")
                continue
            
            try:
                result = await self.check_file(file_path, file_content, model)
                if result.get('type') == 'malicious':
                    logger.warning(f"Malicious code detected in {file_path} by model {model}")
                    return result
                # If normal, try next model for confirmation
                logger.debug(f"File {file_path} marked as normal by model {model}")
            except Exception as e:
                logger.warning(f"Error with model {model} for {file_path}: {str(e)}")
                continue
        
        # If all models say normal, return normal
        logger.info(f"File {file_path} verified safe by all models")
        return {'type': 'normal', 'statement': 'Code verified safe'}
    
    def read_file_safe(self, file_path: Path, max_size: Optional[int] = None) -> str:
        """
        Safely read file content with size limit.
        
        Args:
            file_path: Path to the file
            max_size: Maximum file size to read (uses config default if None)
            
        Returns:
            str: File content or error message
        """
        try:
            max_size = max_size or MAX_FILE_SIZE
            
            if not file_path.exists():
                logger.warning(f"File not found: {file_path}")
                return f"[Error: File not found]"
            
            file_size = file_path.stat().st_size
            if file_size > max_size:
                logger.warning(f"File too large: {file_path} ({file_size} bytes)")
                return f"[File too large: {file_size} bytes]"
            
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            logger.debug(f"Successfully read file {file_path} ({len(content)} bytes)")
            return content
        except PermissionError:
            logger.error(f"Permission denied reading file: {file_path}")
            return f"[Error: Permission denied]"
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {str(e)}", exc_info=True)
            return f"[Error reading file: {str(e)}]"
    
    async def scan_files(
        self, 
        project_dir: Path, 
        file_paths: List[str], 
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Dict]:
        """
        Scan multiple files concurrently with progress updates.
        
        Args:
            project_dir: Project directory path
            file_paths: List of relative file paths to scan
            progress_callback: Optional async callback for progress updates
            
        Returns:
            dict: Mapping of file paths to scan results
        """
        logger.info(f"Starting security scan for {len(file_paths)} files in {project_dir}")
        
        # Filter to only check code files
        code_extensions = ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.php', '.rb']
        code_files = [f for f in file_paths if any(f.endswith(ext) for ext in code_extensions)]
        
        if not code_files:
            logger.info("No code files found to scan")
            return {f: {'type': 'normal', 'statement': 'Not a code file'} for f in file_paths}
        
        logger.info(f"Found {len(code_files)} code files to scan")
        
        # Read all file contents first
        file_contents = {}
        for file_path in code_files:
            try:
                full_path = project_dir / file_path
                if full_path.is_file():
                    content = self.read_file_safe(full_path)
                    file_contents[file_path] = content
                else:
                    logger.warning(f"File path is not a file: {full_path}")
            except Exception as e:
                logger.error(f"Error processing file {file_path}: {str(e)}", exc_info=True)
                file_contents[file_path] = f"[Error reading file: {str(e)}]"
        
        # Process files in batches for better progress updates
        batch_size = SECURITY_BATCH_SIZE
        scan_results = {}
        total_files = len(code_files)
        
        logger.info(f"Scanning {total_files} files in batches of {batch_size}")
        
        for batch_start in range(0, total_files, batch_size):
            batch_files = code_files[batch_start:batch_start + batch_size]
            tasks = []
            
            for file_path in batch_files:
                if file_path in file_contents:
                    tasks.append(self.check_file_with_retry(file_path, file_contents[file_path]))
                else:
                    logger.warning(f"File content not available for {file_path}")
            
            # Run batch checks concurrently
            try:
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                logger.error(f"Error in batch scan: {str(e)}", exc_info=True)
                batch_results = [Exception(f"Batch scan error: {str(e)}")] * len(batch_files)
            
            # Process batch results
            for i, file_path in enumerate(batch_files):
                if i < len(batch_results):
                    if isinstance(batch_results[i], Exception):
                        error_msg = str(batch_results[i])
                        logger.error(f"Error scanning {file_path}: {error_msg}")
                        scan_results[file_path] = {'type': 'normal', 'statement': f'Error: {error_msg[:100]}'}
                    else:
                        scan_results[file_path] = batch_results[i]
                else:
                    logger.warning(f"No result for {file_path}")
                    scan_results[file_path] = {'type': 'normal', 'statement': 'Not scanned'}
            
            # Update progress
            if progress_callback:
                try:
                    await progress_callback(batch_files, scan_results)
                except Exception as e:
                    logger.error(f"Error in progress callback: {str(e)}", exc_info=True)
        
        # Add non-code files as normal
        for file_path in file_paths:
            if file_path not in scan_results:
                scan_results[file_path] = {'type': 'normal', 'statement': 'Not a code file'}
        
        # Count results
        malicious_count = sum(1 for r in scan_results.values() if r.get('type') == 'malicious')
        logger.info(f"Security scan complete: {malicious_count} malicious, {len(scan_results) - malicious_count} safe")
        
        return scan_results

